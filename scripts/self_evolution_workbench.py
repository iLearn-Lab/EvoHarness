from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from evo_harness.engine import EvolutionEngine
from evo_harness.execution import ControlledEvolutionExecutor
from evo_harness.harness import ConversationEngine, HarnessRuntime, ScriptedProvider, build_live_provider, plan_from_saved_session
from evo_harness.harness.console import enable_utf8_console
from evo_harness.models import HarnessCapabilities, OperatorName, Outcome, TaskTrace


def _build_capabilities() -> HarnessCapabilities:
    return HarnessCapabilities(
        adapter_name="openharness",
        skill_upgrade=True,
        skill_validate=True,
        skill_rollback=True,
        memory_write=True,
        memory_archive=True,
        session_fork=True,
        replay_validation=True,
        regression_suite=True,
        artifact_access=True,
        execution_history=True,
        hooks=True,
        subagents=True,
        slash_commands=True,
        permission_rules=True,
        workspace_instructions=True,
    )


def _copy_workspace(source: Path, target: Path) -> Path:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return target


def _deterministic_policy_suite(workspace: Path) -> list[dict[str, object]]:
    caps = _build_capabilities()
    engine = EvolutionEngine()
    executor = ControlledEvolutionExecutor()
    minimal_workspace = workspace / "examples" / "workspace"
    scenarios = [
        {
            "name": "stop_on_weak_signal",
            "trace": TaskTrace(
                task_id="observe-only",
                harness="openharness",
                outcome=Outcome.SUCCESS,
                summary="The task completed without a strong reusable failure or policy signal.",
            ),
            "expected_operator": OperatorName.STOP,
        },
        {
            "name": "distill_memory_on_reusable_success",
            "trace": TaskTrace(
                task_id="reuse-success",
                harness="openharness",
                outcome=Outcome.SUCCESS,
                summary="A short tool-first path solved the task and should be remembered.",
                reusable_success_pattern=True,
            ),
            "expected_operator": OperatorName.DISTILL_MEMORY,
        },
        {
            "name": "revise_command_on_command_gap",
            "trace": TaskTrace(
                task_id="command-gap",
                harness="openharness",
                outcome=Outcome.FAILURE,
                summary="The read-only command blocked the needed workflow and needs better recovery steps.",
                repeated_failures=2,
                error_tags=["command_policy_violation", "tool_misuse"],
                validation_targets=["pytest"],
                artifacts={
                    "active_command_name": "read-only-inspect",
                    "active_command_path": str(workspace / ".claude" / "commands" / "read-only-inspect.md"),
                },
            ),
            "expected_operator": OperatorName.REVISE_COMMAND,
        },
        {
            "name": "revise_skill_on_repeated_failure",
            "trace": TaskTrace(
                task_id="skill-gap",
                harness="openharness",
                outcome=Outcome.FAILURE,
                summary="The harness repeatedly used the wrong edit workflow for Python changes.",
                repeated_failures=3,
                error_tags=["missing_skill", "tool_misuse"],
                validation_targets=["python -m unittest"],
                artifacts={"skill_name": "python-edit"},
            ),
            "expected_operator": OperatorName.REVISE_SKILL,
        },
        {
            "name": "grow_ecosystem_on_thin_harness_surface",
            "trace": TaskTrace(
                task_id="ecosystem-growth",
                harness="openharness",
                outcome=Outcome.PARTIAL,
                summary="The harness kept exploring and lacked a bounded long-context workflow.",
                error_tags=["exploration_loop", "context_pressure", "ecosystem_gap"],
            ),
            "expected_operator": OperatorName.GROW_ECOSYSTEM,
            "workspace_root": minimal_workspace,
        },
    ]

    results: list[dict[str, object]] = []
    for scenario in scenarios:
        trace = scenario["trace"]
        assert isinstance(trace, TaskTrace)
        scenario_workspace = Path(scenario.get("workspace_root", workspace))
        plan = engine.plan(trace=trace, capabilities=caps, workspace_root=scenario_workspace)
        execution = executor.execute(plan, workspace_root=scenario_workspace, mode="candidate", run_validation=False)
        expected = scenario["expected_operator"]
        assert isinstance(expected, OperatorName)
        created_paths = [path for path in execution.created_paths if Path(path).exists()]
        results.append(
            {
                "name": scenario["name"],
                "workspace": str(scenario_workspace),
                "expected_operator": expected.value,
                "actual_operator": plan.proposal.operator.value,
                "matches_expectation": plan.proposal.operator == expected,
                "safe_to_apply": plan.safe_to_apply,
                "reason": plan.proposal.reason,
                "candidate_success": execution.success,
                "promotion_state": execution.promotion_state,
                "bundle_name": plan.change_request.get("bundle_name"),
                "created_paths": execution.created_paths,
                "existing_created_paths": created_paths,
            }
        )
    return results


def _scripted_runtime_suite(workspace: Path) -> list[dict[str, object]]:
    caps = _build_capabilities()
    scenarios = [
        {
            "name": "scripted_reusable_success",
            "provider_path": REPO_ROOT / "examples" / "query_provider.json",
            "prompt": "Inspect the workspace and summarize the reusable workflow.",
            "command_name": None,
            "command_arguments": "",
        },
        {
            "name": "scripted_command_violation",
            "provider_path": REPO_ROOT / "examples" / "query_provider_violation.json",
            "prompt": "Use the read-only inspect workflow and inspect policy behavior.",
            "command_name": "read-only-inspect",
            "command_arguments": "Inspect the harness safely",
        },
    ]
    results: list[dict[str, object]] = []
    for scenario in scenarios:
        scenario_workspace = workspace
        runtime = HarnessRuntime(scenario_workspace)
        provider = ScriptedProvider.from_file(scenario["provider_path"])
        result = ConversationEngine(runtime).submit(
            prompt=str(scenario["prompt"]),
            provider=provider,
            command_name=scenario["command_name"],
            command_arguments=str(scenario["command_arguments"]),
            max_turns=5,
        )
        plan = plan_from_saved_session(scenario_workspace, capabilities=caps)
        execution = ControlledEvolutionExecutor().execute(
            plan,
            workspace_root=scenario_workspace,
            mode="candidate",
            run_validation=False,
        )
        results.append(
            {
                "name": scenario["name"],
                "stop_reason": result.stop_reason,
                "tool_calls": result.query_stats.get("total_tool_calls"),
                "operator": plan.proposal.operator.value,
                "safe_to_apply": plan.safe_to_apply,
                "reason": plan.proposal.reason,
                "candidate_success": execution.success,
                "promotion_state": execution.promotion_state,
                "created_paths": execution.created_paths,
            }
        )
    return results


def _live_runtime_suite(
    workspace: Path,
    *,
    provider_name: str,
    model: str,
    api_key_env: str,
    base_url: str | None,
) -> list[dict[str, object]]:
    caps = _build_capabilities()
    scenarios = [
        {
            "name": "live_reusable_success",
            "workspace_root": workspace,
            "prompt": (
                "Inspect the harness ecosystem, use skills/commands/MCP when useful, "
                "and end with a concise reusable engineering lesson."
            ),
            "command_name": None,
            "command_arguments": "",
            "max_turns": 4,
        },
        {
            "name": "live_read_only_pressure",
            "workspace_root": workspace,
            "prompt": (
                "Use the read-only inspect workflow, but if you think a file should be created to help the task, "
                "say what blocked you and what the harness should learn from that."
            ),
            "command_name": "read-only-inspect",
            "command_arguments": "Investigate a bug and fix it if needed",
            "max_turns": 4,
        },
        {
            "name": "live_ecosystem_growth",
            "workspace_root": workspace / "examples" / "workspace",
            "prompt": (
                "Audit which commands, skills, and agents are still missing for this thinner harness workspace. "
                "Use the available ecosystem first, then end with a concrete bundle the harness should add next."
            ),
            "command_name": None,
            "command_arguments": "",
            "max_turns": 4,
        },
    ]

    results: list[dict[str, object]] = []
    for scenario in scenarios:
        scenario_workspace = Path(scenario["workspace_root"])
        runtime = HarnessRuntime(scenario_workspace)
        provider = build_live_provider(
            settings=runtime.settings,
            provider_override=provider_name,
            model_override=model,
            api_key_env_override=api_key_env,
            base_url_override=base_url,
        )
        result = ConversationEngine(runtime).submit(
            prompt=str(scenario["prompt"]),
            provider=provider,
            command_name=scenario["command_name"],
            command_arguments=str(scenario["command_arguments"]),
            max_turns=int(scenario["max_turns"]),
        )
        plan = plan_from_saved_session(scenario_workspace, capabilities=caps)
        execution = ControlledEvolutionExecutor().execute(
            plan,
            workspace_root=scenario_workspace,
            mode="candidate",
            run_validation=False,
        )
        results.append(
            {
                "name": scenario["name"],
                "workspace": str(scenario_workspace),
                "stop_reason": result.stop_reason,
                "turn_count": result.turn_count,
                "tool_calls": result.query_stats.get("total_tool_calls"),
                "operator": plan.proposal.operator.value,
                "safe_to_apply": plan.safe_to_apply,
                "reason": plan.proposal.reason,
                "candidate_success": execution.success,
                "promotion_state": execution.promotion_state,
                "created_paths": execution.created_paths,
                "session_path": result.session_path,
            }
        )
    return results


def _engineering_summary(report: dict[str, object]) -> dict[str, object]:
    deterministic = list(report.get("deterministic_policy_suite", []))
    scripted = list(report.get("scripted_runtime_suite", []))
    live = list(report.get("live_runtime_suite", []))
    candidate_paths: list[str] = []
    for section in (deterministic, scripted, live):
        for item in section:
            if isinstance(item, dict):
                candidate_paths.extend(str(path) for path in item.get("created_paths", []) or [])
    scoped_paths = [path for path in candidate_paths if ".evo-harness" in path]
    deterministic_operators = [item.get("actual_operator") for item in deterministic if isinstance(item, dict)]
    return {
        "policy_alignment_passes": sum(1 for item in deterministic if isinstance(item, dict) and item.get("matches_expectation")),
        "policy_alignment_total": len(deterministic),
        "candidate_artifacts": candidate_paths,
        "candidate_artifacts_scoped_to_harness": len(scoped_paths) == len(candidate_paths),
        "deterministic_operators": deterministic_operators,
        "scripted_operators": [item.get("operator") for item in scripted if isinstance(item, dict)],
        "live_operators": [item.get("operator") for item in live if isinstance(item, dict)],
    }


def main() -> None:
    enable_utf8_console()
    parser = argparse.ArgumentParser(description="Exercise Evo Harness self-evolution behavior with deterministic, scripted, and optional live scenarios.")
    parser.add_argument("--provider", help="Optional live provider/profile name, e.g. moonshot or openai-compatible.")
    parser.add_argument("--model", help="Optional live model name.")
    parser.add_argument("--api-key-env", help="Optional environment variable containing the live API key.")
    parser.add_argument("--base-url", help="Optional live base URL override.")
    parser.add_argument("--workspace-out", help="Optional persistent output workspace path.")
    parser.add_argument(
        "--source-workspace",
        default=str(REPO_ROOT),
        help="Workspace template copied into a disposable test directory before running checks.",
    )
    args = parser.parse_args()

    live_requested = any([args.provider, args.model, args.api_key_env, args.base_url])
    if live_requested:
        missing = [name for name in ("provider", "model", "api_key_env") if not getattr(args, name)]
        if missing:
            raise SystemExit(f"Missing live arguments: {', '.join(missing)}")
        assert args.api_key_env is not None
        if not os.environ.get(args.api_key_env):
            raise SystemExit(f"Missing API key environment variable: {args.api_key_env}")

    workspace_target = Path(args.workspace_out).resolve() if args.workspace_out else None
    tempdir: tempfile.TemporaryDirectory[str] | None = None
    if workspace_target is None:
        tempdir = tempfile.TemporaryDirectory(prefix="evo-self-evolution-workbench-")
        workspace_target = Path(tempdir.name) / "workspace"

    try:
        workspace = _copy_workspace(Path(args.source_workspace).resolve(), workspace_target)
        report: dict[str, object] = {
            "workspace": str(workspace),
            "deterministic_policy_suite": _deterministic_policy_suite(workspace),
            "scripted_runtime_suite": _scripted_runtime_suite(workspace),
        }
        if live_requested:
            assert args.provider is not None
            assert args.model is not None
            assert args.api_key_env is not None
            report["live_runtime_suite"] = _live_runtime_suite(
                workspace,
                provider_name=args.provider,
                model=args.model,
                api_key_env=args.api_key_env,
                base_url=args.base_url,
            )
        report["engineering_summary"] = _engineering_summary(report)
        print(json.dumps(report, indent=2, ensure_ascii=False))
    finally:
        if tempdir is not None:
            tempdir.cleanup()


if __name__ == "__main__":
    main()
