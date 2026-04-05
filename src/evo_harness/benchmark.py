from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from evo_harness.harness import (
    HarnessRuntime,
    QueryRunResult,
    ScriptedProvider,
    build_live_provider,
    detect_provider_profile,
    run_query,
)


@dataclass(slots=True)
class BenchmarkCase:
    case_id: str
    prompt: str
    command_name: str | None = None
    command_arguments: str = ""
    max_turns: int = 8
    contains_all: list[str] = field(default_factory=list)
    contains_any: list[str] = field(default_factory=list)
    forbidden_text: list[str] = field(default_factory=list)
    expected_stop_reason: str | None = None
    max_tool_calls: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BenchmarkCaseResult:
    case_id: str
    success: bool
    score: float
    reasons: list[str]
    stop_reason: str | None
    tool_calls: int
    turn_count: int
    session_path: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BenchmarkRun:
    workspace: str
    provider_label: str
    model: str
    dataset_path: str
    results: list[BenchmarkCaseResult]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace": self.workspace,
            "provider_label": self.provider_label,
            "model": self.model,
            "dataset_path": self.dataset_path,
            "created_at": self.created_at,
            "results": [item.to_dict() for item in self.results],
            "summary": benchmark_summary(self),
        }


def load_benchmark_cases(path: str | Path) -> list[BenchmarkCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        BenchmarkCase(
            case_id=str(item["case_id"]),
            prompt=str(item["prompt"]),
            command_name=item.get("command_name"),
            command_arguments=str(item.get("command_arguments", "")),
            max_turns=int(item.get("max_turns", 8)),
            contains_all=[str(part) for part in item.get("contains_all", [])],
            contains_any=[str(part) for part in item.get("contains_any", [])],
            forbidden_text=[str(part) for part in item.get("forbidden_text", [])],
            expected_stop_reason=item.get("expected_stop_reason"),
            max_tool_calls=int(item["max_tool_calls"]) if item.get("max_tool_calls") is not None else None,
        )
        for item in payload.get("cases", [])
    ]


def run_benchmark(
    workspace: str | Path,
    *,
    dataset_path: str | Path,
    provider_factory: Callable[[], Any],
    settings_path: str | Path | None = None,
    provider_label: str,
) -> BenchmarkRun:
    runtime = HarnessRuntime(workspace, settings_path=settings_path)
    cases = load_benchmark_cases(dataset_path)
    results: list[BenchmarkCaseResult] = []
    for case in cases:
        runtime.reset()
        provider = provider_factory()
        query_result = run_query(
            runtime,
            prompt=case.prompt,
            provider=provider,
            command_name=case.command_name,
            command_arguments=case.command_arguments,
            max_turns=case.max_turns,
        )
        results.append(_judge_case(case, query_result))
    return BenchmarkRun(
        workspace=str(Path(workspace).resolve()),
        provider_label=provider_label,
        model=runtime.settings.model,
        dataset_path=str(Path(dataset_path).resolve()),
        results=results,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def write_benchmark_run(workspace: str | Path, run: BenchmarkRun) -> Path:
    root = Path(workspace).resolve() / ".evo-harness" / "benchmarks"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(run.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def benchmark_summary(run: BenchmarkRun) -> dict[str, Any]:
    total = len(run.results)
    passed = sum(1 for item in run.results if item.success)
    avg_score = round(sum(item.score for item in run.results) / total, 3) if total else 0.0
    return {
        "total_cases": total,
        "passed_cases": passed,
        "failed_cases": total - passed,
        "avg_score": avg_score,
    }


def compare_benchmark_runs(left_path: str | Path, right_path: str | Path) -> dict[str, Any]:
    left = json.loads(Path(left_path).read_text(encoding="utf-8"))
    right = json.loads(Path(right_path).read_text(encoding="utf-8"))
    left_results = {item["case_id"]: item for item in left.get("results", [])}
    right_results = {item["case_id"]: item for item in right.get("results", [])}
    case_ids = sorted(set(left_results) | set(right_results))
    comparisons: list[dict[str, Any]] = []
    for case_id in case_ids:
        left_item = left_results.get(case_id)
        right_item = right_results.get(case_id)
        comparisons.append(
            {
                "case_id": case_id,
                "left_score": left_item.get("score") if left_item else None,
                "right_score": right_item.get("score") if right_item else None,
                "left_success": left_item.get("success") if left_item else None,
                "right_success": right_item.get("success") if right_item else None,
                "delta_score": (
                    round(float(right_item["score"]) - float(left_item["score"]), 3)
                    if left_item is not None and right_item is not None
                    else None
                ),
            }
        )
    return {
        "left": {
            "path": str(Path(left_path).resolve()),
            "summary": left.get("summary", {}),
            "provider_label": left.get("provider_label"),
        },
        "right": {
            "path": str(Path(right_path).resolve()),
            "summary": right.get("summary", {}),
            "provider_label": right.get("provider_label"),
        },
        "cases": comparisons,
    }


def build_provider_factory(
    *,
    workspace: str | Path,
    settings_path: str | Path | None = None,
    provider_script: str | Path | None = None,
) -> tuple[Callable[[], Any], str]:
    runtime = HarnessRuntime(workspace, settings_path=settings_path)
    if provider_script is not None:
        provider_path = str(Path(provider_script).resolve())
        return (lambda: ScriptedProvider.from_file(provider_path), f"scripted:{Path(provider_path).name}")
    profile = detect_provider_profile(
        provider=runtime.settings.provider.provider,
        profile=runtime.settings.provider.profile,
        base_url=runtime.settings.provider.base_url,
        model=runtime.settings.model,
    )
    return (lambda: build_live_provider(settings=runtime.settings), f"live:{profile.name}")


def _judge_case(case: BenchmarkCase, result: QueryRunResult) -> BenchmarkCaseResult:
    summary = _best_summary(result.messages)
    score = 1.0
    reasons: list[str] = []
    text = summary.lower()
    for expected in case.contains_all:
        if expected.lower() not in text:
            score -= 0.25
            reasons.append(f"missing:{expected}")
    if case.contains_any:
        if not any(part.lower() in text for part in case.contains_any):
            score -= 0.20
            reasons.append("missing_any")
    for forbidden in case.forbidden_text:
        if forbidden.lower() in text:
            score -= 0.25
            reasons.append(f"forbidden:{forbidden}")
    if case.expected_stop_reason and result.stop_reason != case.expected_stop_reason:
        score -= 0.15
        reasons.append(f"stop_reason:{result.stop_reason}")
    if case.max_tool_calls is not None and int(result.query_stats.get("total_tool_calls", 0)) > case.max_tool_calls:
        score -= 0.15
        reasons.append("too_many_tool_calls")
    score = max(0.0, min(score, 1.0))
    return BenchmarkCaseResult(
        case_id=case.case_id,
        success=score >= 0.6,
        score=score,
        reasons=reasons,
        stop_reason=result.stop_reason,
        tool_calls=int(result.query_stats.get("total_tool_calls", 0)),
        turn_count=result.turn_count,
        session_path=result.session_path,
        summary=summary,
    )


def _best_summary(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "assistant" and str(message.get("text", "")).strip():
            return str(message.get("text", "")).strip()
    for message in reversed(messages):
        if str(message.get("text", "")).strip():
            return str(message.get("text", "")).strip()
    return ""
