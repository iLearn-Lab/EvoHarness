from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evo_harness.harness.memory import add_memory_entry
from evo_harness.harness.settings import load_settings
from evo_harness.models import EvolutionPlan, OperatorName


@dataclass(slots=True)
class ValidationResult:
    step: str
    success: bool
    output: str = ""
    executed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PromotionAssessment:
    score: float
    decision: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExecutionResult:
    operator: str
    mode: str
    success: bool
    promotion_state: str = "none"
    applied_paths: list[str] = field(default_factory=list)
    created_paths: list[str] = field(default_factory=list)
    backup_paths: list[str] = field(default_factory=list)
    validation: list[ValidationResult] = field(default_factory=list)
    assessment: PromotionAssessment | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator": self.operator,
            "mode": self.mode,
            "success": self.success,
            "promotion_state": self.promotion_state,
            "applied_paths": self.applied_paths,
            "created_paths": self.created_paths,
            "backup_paths": self.backup_paths,
            "validation": [item.to_dict() for item in self.validation],
            "assessment": self.assessment.to_dict() if self.assessment is not None else None,
            "notes": self.notes,
        }


@dataclass(slots=True)
class RollbackResult:
    success: bool
    restored_paths: list[str] = field(default_factory=list)
    removed_paths: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ControlledEvolutionExecutor:
    """Safely apply evolution plans with candidate/apply/promote modes and rollback support."""

    def execute(
        self,
        plan: EvolutionPlan,
        *,
        workspace_root: str | Path,
        mode: str = "candidate",
        run_validation: bool = False,
        allow_unvalidated_promotion: bool = False,
    ) -> ExecutionResult:
        workspace = Path(workspace_root).resolve()
        settings = load_settings(workspace=workspace)
        operator = plan.proposal.operator
        if operator == OperatorName.STOP:
            return ExecutionResult(
                operator=operator.value,
                mode=mode,
                success=True,
                promotion_state="skipped",
                notes=["No mutation executed because the plan selected stop."],
            )
        normalized_mode = "promote" if mode == "auto" else mode
        if operator == OperatorName.REVISE_SKILL:
            return self._execute_text_artifact_revision(
                plan,
                workspace=workspace,
                mode=normalized_mode,
                run_validation=run_validation or mode == "auto",
                allow_unvalidated_promotion=allow_unvalidated_promotion,
                policy=settings.promotion,
                safety=settings.safety,
                artifact_kind="skills",
                default_target=workspace / ".openharness" / "skills" / "generated_fix.md",
                default_header="Generated Skill",
                success_note="Applied the evolution plan directly to the target skill.",
            )
        if operator == OperatorName.REVISE_COMMAND:
            return self._execute_text_artifact_revision(
                plan,
                workspace=workspace,
                mode=normalized_mode,
                run_validation=run_validation or mode == "auto",
                allow_unvalidated_promotion=allow_unvalidated_promotion,
                policy=settings.promotion,
                safety=settings.safety,
                artifact_kind="commands",
                default_target=workspace / ".claude" / "commands" / "generated_fix.md",
                default_header="Generated Command",
                success_note="Applied the evolution plan directly to the target command.",
            )
        if operator == OperatorName.GROW_ECOSYSTEM:
            return self._execute_ecosystem_growth(
                plan,
                workspace=workspace,
                mode=normalized_mode,
                run_validation=run_validation or mode == "auto",
                allow_unvalidated_promotion=allow_unvalidated_promotion,
                policy=settings.promotion,
                safety=settings.safety,
            )
        if operator == OperatorName.DISTILL_MEMORY:
            return self._execute_distill_memory(
                plan,
                workspace=workspace,
                mode=normalized_mode,
                run_validation=run_validation or mode == "auto",
                allow_unvalidated_promotion=allow_unvalidated_promotion,
                policy=settings.promotion,
                safety=settings.safety,
            )
        return ExecutionResult(
            operator=operator.value,
            mode=mode,
            success=False,
            promotion_state="unsupported",
            notes=[f"Unsupported operator: {operator.value}"],
        )

    def _execute_text_artifact_revision(
        self,
        plan: EvolutionPlan,
        *,
        workspace: Path,
        mode: str,
        run_validation: bool,
        allow_unvalidated_promotion: bool,
        policy,
        safety,
        artifact_kind: str,
        default_target: Path,
        default_header: str,
        success_note: str,
    ) -> ExecutionResult:
        result = ExecutionResult(operator=plan.proposal.operator.value, mode=mode, success=True)
        target = Path(plan.change_request.get("preferred_path", default_target))
        if not target.is_absolute():
            target = (workspace / target).resolve()
        original = target.read_text(encoding="utf-8") if target.exists() else f"# {default_header}\n"
        candidate_dir, rollback_dir = _candidate_and_rollback_dirs(workspace, artifact_kind)
        backup_path = rollback_dir / target.name
        if target.exists():
            shutil.copy2(target, backup_path)
            result.backup_paths.append(str(backup_path))

        updated = _merge_text_artifact_update(original, plan)

        if mode == "candidate":
            candidate_path = candidate_dir / f"{target.stem}.candidate{target.suffix}"
            candidate_path.write_text(updated, encoding="utf-8")
            result.created_paths.append(str(candidate_path))
            result.notes.append(f"Wrote a candidate {artifact_kind[:-1]} file without mutating the original.")
            result.promotion_state = "candidate_only"
        elif mode == "apply":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(updated, encoding="utf-8")
            result.applied_paths.append(str(target))
            result.notes.append(success_note)
            result.promotion_state = "applied"
        elif mode == "promote":
            candidate_path = candidate_dir / f"{target.stem}.candidate{target.suffix}"
            candidate_path.write_text(updated, encoding="utf-8")
            result.created_paths.append(str(candidate_path))
            result.notes.append(f"Created candidate {artifact_kind[:-1]} before promotion.")
        else:
            result.success = False
            result.promotion_state = "invalid_mode"
            result.notes.append(f"Unknown execution mode: {mode}")
            return result

        result.validation = _run_validation_steps(plan, workspace, run_validation=run_validation)
        if mode == "apply" and any(not item.success for item in result.validation):
            if safety.rollback_on_apply_validation_failure:
                _restore_backups(result.backup_paths, result.applied_paths)
                result.notes.append("Validation failed; restored the original artifact from backup.")
                result.promotion_state = "rolled_back"
            result.success = False
        if mode == "promote":
            validation_decision, assessment = _promotion_decision(
                result.validation,
                plan=plan,
                allow_unvalidated_promotion=allow_unvalidated_promotion,
                workspace=workspace,
                policy=policy,
            )
            result.assessment = assessment
            if validation_decision == "promote":
                target.parent.mkdir(parents=True, exist_ok=True)
                candidate_path = Path(result.created_paths[0])
                shutil.copy2(candidate_path, target)
                result.applied_paths.append(str(target))
                result.promotion_state = "promoted"
                result.notes.append(f"Promoted candidate {artifact_kind[:-1]} to the active target.")
            elif validation_decision == "blocked":
                result.success = False
                result.promotion_state = "blocked"
                result.notes.append("Promotion blocked because the gating policy was not satisfied.")
            else:
                result.success = False
                result.promotion_state = "rejected"
                result.notes.append("Promotion rejected because validation or history gates failed.")

        return result

    def _execute_ecosystem_growth(
        self,
        plan: EvolutionPlan,
        *,
        workspace: Path,
        mode: str,
        run_validation: bool,
        allow_unvalidated_promotion: bool,
        policy,
        safety,
    ) -> ExecutionResult:
        result = ExecutionResult(operator=plan.proposal.operator.value, mode=mode, success=True)
        assets = [dict(item) for item in plan.change_request.get("scaffold_assets", [])]
        if not assets:
            result.notes.append("No missing ecosystem assets were selected for scaffolding.")
            result.promotion_state = "skipped"
            return result

        candidate_dir, rollback_dir = _candidate_and_rollback_dirs(workspace, "ecosystem")
        if mode == "candidate":
            for asset in assets:
                candidate_path = _ecosystem_candidate_path(candidate_dir, asset)
                candidate_path.parent.mkdir(parents=True, exist_ok=True)
                candidate_path.write_text(str(asset["content"]).rstrip() + "\n", encoding="utf-8")
                result.created_paths.append(str(candidate_path))
            manifest_path = candidate_dir / f"{plan.trace.task_id}.ecosystem-plan.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "bundle_name": plan.change_request.get("bundle_name"),
                        "summary": plan.change_request.get("summary"),
                        "target_files": plan.change_request.get("target_files", []),
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            result.created_paths.append(str(manifest_path))
            result.notes.append("Wrote candidate ecosystem assets without mutating the active workspace.")
            result.promotion_state = "candidate_only"
        elif mode == "apply":
            for asset in assets:
                target = (workspace / str(asset["target_path"])).resolve()
                if target.exists():
                    backup_path = rollback_dir / target.name
                    shutil.copy2(target, backup_path)
                    result.backup_paths.append(str(backup_path))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(asset["content"]).rstrip() + "\n", encoding="utf-8")
                result.applied_paths.append(str(target))
            result.notes.append("Applied the ecosystem growth bundle to the workspace.")
            result.promotion_state = "applied"
        elif mode == "promote":
            for asset in assets:
                candidate_path = _ecosystem_candidate_path(candidate_dir, asset)
                candidate_path.parent.mkdir(parents=True, exist_ok=True)
                candidate_path.write_text(str(asset["content"]).rstrip() + "\n", encoding="utf-8")
                result.created_paths.append(str(candidate_path))
            result.notes.append("Created candidate ecosystem assets before promotion.")
        else:
            result.success = False
            result.promotion_state = "invalid_mode"
            result.notes.append(f"Unknown execution mode: {mode}")
            return result

        result.validation = _run_validation_steps(plan, workspace, run_validation=run_validation)
        if mode == "apply" and any(not item.success for item in result.validation):
            if safety.rollback_on_apply_validation_failure:
                _restore_backups(result.backup_paths, result.applied_paths)
                result.notes.append("Validation failed; restored the original ecosystem assets from backup.")
                result.promotion_state = "rolled_back"
            result.success = False
        if mode == "promote":
            validation_decision, assessment = _promotion_decision(
                result.validation,
                plan=plan,
                allow_unvalidated_promotion=allow_unvalidated_promotion,
                workspace=workspace,
                policy=policy,
            )
            result.assessment = assessment
            if validation_decision == "promote":
                for asset in assets:
                    target = (workspace / str(asset["target_path"])).resolve()
                    if target.exists():
                        backup_path = rollback_dir / target.name
                        shutil.copy2(target, backup_path)
                        result.backup_paths.append(str(backup_path))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(str(asset["content"]).rstrip() + "\n", encoding="utf-8")
                    result.applied_paths.append(str(target))
                result.promotion_state = "promoted"
                result.notes.append("Promoted the ecosystem growth bundle into the active workspace.")
            elif validation_decision == "blocked":
                result.success = False
                result.promotion_state = "blocked"
                result.notes.append("Promotion blocked because the ecosystem bundle did not satisfy the gates.")
            else:
                result.success = False
                result.promotion_state = "rejected"
                result.notes.append("Promotion rejected because validation or history gates failed.")
        return result

    def _execute_distill_memory(
        self,
        plan: EvolutionPlan,
        *,
        workspace: Path,
        mode: str,
        run_validation: bool,
        allow_unvalidated_promotion: bool,
        policy,
        safety,
    ) -> ExecutionResult:
        result = ExecutionResult(operator=plan.proposal.operator.value, mode=mode, success=True)
        lesson = dict(plan.change_request.get("lesson_template", {}))
        title = str(lesson.get("title", f"Lesson from {plan.trace.task_id}"))
        body = "\n".join(
            [
                f"# {title}",
                "",
                f"- When to use: {lesson.get('when_to_use', '')}",
                f"- Pattern: {lesson.get('pattern', '')}",
                f"- Avoid: {lesson.get('avoid', '')}",
            ]
        ).strip() + "\n"

        if mode == "candidate":
            candidate_dir, _rollback_dir = _candidate_and_rollback_dirs(workspace, "memory")
            candidate_path = candidate_dir / f"{plan.trace.task_id}.memory.md"
            candidate_path.write_text(body, encoding="utf-8")
            result.created_paths.append(str(candidate_path))
            result.notes.append("Wrote a candidate memory entry without touching the workspace memory.")
            result.promotion_state = "candidate_only"
        elif mode == "apply":
            path = add_memory_entry(workspace, title, body)
            result.applied_paths.append(str(path))
            result.notes.append("Added a new memory entry to the workspace.")
            result.promotion_state = "applied"
        elif mode == "promote":
            candidate_dir, _rollback_dir = _candidate_and_rollback_dirs(workspace, "memory")
            candidate_path = candidate_dir / f"{plan.trace.task_id}.memory.md"
            candidate_path.write_text(body, encoding="utf-8")
            result.created_paths.append(str(candidate_path))
            result.notes.append("Created candidate memory entry before promotion.")
        else:
            result.success = False
            result.promotion_state = "invalid_mode"
            result.notes.append(f"Unknown execution mode: {mode}")
            return result

        result.validation = _run_validation_steps(plan, workspace, run_validation=run_validation)
        if mode == "promote":
            validation_decision, assessment = _promotion_decision(
                result.validation,
                plan=plan,
                allow_unvalidated_promotion=allow_unvalidated_promotion,
                workspace=workspace,
                policy=policy,
            )
            result.assessment = assessment
            if validation_decision == "promote":
                path = add_memory_entry(workspace, title, body)
                result.applied_paths.append(str(path))
                result.promotion_state = "promoted"
                result.notes.append("Promoted candidate memory entry into persistent memory.")
            elif validation_decision == "blocked":
                result.success = False
                result.promotion_state = "blocked"
                result.notes.append("Promotion blocked because the gating policy was not satisfied.")
            else:
                result.success = False
                result.promotion_state = "rejected"
                result.notes.append("Promotion rejected because validation or history gates failed.")
        elif any(not item.success for item in result.validation):
            result.success = False
            if mode == "apply":
                if safety.rollback_on_apply_validation_failure:
                    for applied_path in result.applied_paths:
                        path = Path(applied_path)
                        if path.exists():
                            path.unlink()
                    result.notes.append("Validation failed; removed the newly created memory entry.")
                    result.promotion_state = "rolled_back"
                else:
                    result.promotion_state = "applied_with_validation_failure"
        return result


def write_execution_record(
    workspace_root: str | Path,
    *,
    plan: EvolutionPlan,
    execution: ExecutionResult,
) -> Path:
    workspace = Path(workspace_root).resolve()
    path = workspace / ".evo-harness" / "executions"
    path.mkdir(parents=True, exist_ok=True)
    record_path = path / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    record_path.write_text(
        json.dumps(
            {
                "plan": plan.to_dict(),
                "execution": execution.to_dict(),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return record_path


def list_execution_records(workspace_root: str | Path) -> list[Path]:
    workspace = Path(workspace_root).resolve()
    path = workspace / ".evo-harness" / "executions"
    if not path.exists():
        return []
    return sorted(path.glob("*.json"), reverse=True)


def promotion_report(workspace_root: str | Path, *, limit: int = 50) -> dict[str, Any]:
    workspace = Path(workspace_root).resolve()
    records = list_execution_records(workspace)[:limit]
    totals = {
        "total_records": 0,
        "promoted": 0,
        "blocked": 0,
        "rejected": 0,
        "rolled_back": 0,
        "applied": 0,
        "candidate_only": 0,
    }
    by_target: dict[str, dict[str, int]] = {}
    by_bundle: dict[str, dict[str, int]] = {}
    recent: list[dict[str, Any]] = []
    for path in records:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        execution = payload.get("execution", {})
        plan = payload.get("plan", {})
        state = str(execution.get("promotion_state", "none"))
        target = _plan_target_label(plan)
        bundle_name = _plan_bundle_name(plan)
        assessment = execution.get("assessment") or {}
        totals["total_records"] += 1
        if state in totals:
            totals[state] += 1
        target_stats = by_target.setdefault(
            target,
            {"promoted": 0, "blocked": 0, "rejected": 0, "rolled_back": 0, "applied": 0, "candidate_only": 0},
        )
        if state in target_stats:
            target_stats[state] += 1
        if bundle_name:
            bundle_stats = by_bundle.setdefault(
                bundle_name,
                {"promoted": 0, "blocked": 0, "rejected": 0, "rolled_back": 0, "applied": 0, "candidate_only": 0},
            )
            if state in bundle_stats:
                bundle_stats[state] += 1
        recent.append(
            {
                "record": str(path),
                "operator": execution.get("operator"),
                "mode": execution.get("mode"),
                "promotion_state": state,
                "score": assessment.get("score"),
                "decision": assessment.get("decision"),
                "target": target,
                "bundle": bundle_name,
            }
        )
    return {"totals": totals, "by_target": by_target, "by_bundle": by_bundle, "recent": recent}


def promotion_analytics_report(workspace_root: str | Path, *, limit: int = 100) -> dict[str, Any]:
    workspace = Path(workspace_root).resolve()
    records = list_execution_records(workspace)[:limit]
    by_operator: dict[str, int] = {}
    by_decision: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    scores: list[float] = []
    target_health: dict[str, dict[str, int]] = {}
    bundle_health: dict[str, dict[str, int]] = {}
    recent: list[dict[str, Any]] = []

    for path in records:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        execution = dict(payload.get("execution", {}))
        plan = dict(payload.get("plan", {}))
        operator = str(execution.get("operator", "unknown"))
        assessment = dict(execution.get("assessment") or {})
        decision = str(assessment.get("decision", execution.get("promotion_state", "unknown")))
        target = _plan_target_label(plan)
        bundle_name = _plan_bundle_name(plan)
        by_operator[operator] = by_operator.get(operator, 0) + 1
        by_decision[decision] = by_decision.get(decision, 0) + 1
        for reason in assessment.get("reasons", []):
            by_reason[str(reason)] = by_reason.get(str(reason), 0) + 1
        if assessment.get("score") is not None:
            try:
                scores.append(float(assessment["score"]))
            except (TypeError, ValueError):
                pass
        health = target_health.setdefault(target, {"promoted": 0, "blocked": 0, "rejected": 0, "rolled_back": 0, "applied": 0})
        state = str(execution.get("promotion_state", "unknown"))
        if state in health:
            health[state] += 1
        if bundle_name:
            bundle_state = bundle_health.setdefault(bundle_name, {"promoted": 0, "blocked": 0, "rejected": 0, "rolled_back": 0, "applied": 0, "candidate_only": 0})
            if state in bundle_state:
                bundle_state[state] += 1
        recent.append(
            {
                "record": str(path),
                "operator": operator,
                "decision": decision,
                "score": assessment.get("score"),
                "target": target,
                "bundle": bundle_name,
            }
        )

    return {
        "totals": {
            "records": len(recent),
            "avg_score": round(sum(scores) / len(scores), 3) if scores else None,
            "max_score": max(scores) if scores else None,
            "min_score": min(scores) if scores else None,
        },
        "by_operator": dict(sorted(by_operator.items(), key=lambda item: item[0])),
        "by_decision": dict(sorted(by_decision.items(), key=lambda item: item[0])),
        "top_reasons": [{"reason": reason, "count": count} for reason, count in sorted(by_reason.items(), key=lambda item: item[1], reverse=True)[:10]],
        "target_health": target_health,
        "bundle_health": bundle_health,
        "recent": recent[:15],
    }


def rollback_execution(
    workspace_root: str | Path,
    *,
    record_path: str | Path | None = None,
) -> RollbackResult:
    workspace = Path(workspace_root).resolve()
    selected = Path(record_path).resolve() if record_path is not None else None
    if selected is None:
        records = list_execution_records(workspace)
        if not records:
            return RollbackResult(success=False, notes=["No execution records found to roll back."])
        selected = records[0]
    if not selected.exists():
        return RollbackResult(success=False, notes=[f"Execution record not found: {selected}"])

    payload = json.loads(selected.read_text(encoding="utf-8"))
    execution = dict(payload.get("execution", {}))
    backup_paths = [Path(path) for path in execution.get("backup_paths", [])]
    applied_paths = [Path(path) for path in execution.get("applied_paths", [])]
    created_paths = [Path(path) for path in execution.get("created_paths", [])]

    restored: list[str] = []
    removed: list[str] = []
    if backup_paths:
        for backup in backup_paths:
            if not backup.exists():
                continue
            target = _restore_target_from_backup(backup, applied_paths)
            if target is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
            restored.append(str(target))
    else:
        for target in applied_paths:
            if target.exists():
                target.unlink()
                removed.append(str(target))
        for target in created_paths:
            if target.exists():
                target.unlink()
                removed.append(str(target))

    rollback_result = RollbackResult(
        success=bool(restored or removed),
        restored_paths=restored,
        removed_paths=removed,
        notes=[f"Rolled back using execution record: {selected}"] if restored or removed else ["No files were restored."],
    )
    rollback_dir = workspace / ".evo-harness" / "executions"
    rollback_dir.mkdir(parents=True, exist_ok=True)
    rollback_record = rollback_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.rollback.json"
    rollback_record.write_text(
        json.dumps({"source_record": str(selected), "rollback": rollback_result.to_dict()}, indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return rollback_result


def _candidate_and_rollback_dirs(workspace: Path, artifact_kind: str) -> tuple[Path, Path]:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate_dir = workspace / ".evo-harness" / "candidates" / artifact_kind
    rollback_dir = workspace / ".evo-harness" / "rollbacks" / timestamp
    candidate_dir.mkdir(parents=True, exist_ok=True)
    rollback_dir.mkdir(parents=True, exist_ok=True)
    return candidate_dir, rollback_dir


def _ecosystem_candidate_path(candidate_dir: Path, asset: dict[str, Any]) -> Path:
    kind = str(asset.get("kind", "asset"))
    name = str(asset.get("name", "generated")).replace(" ", "-")
    return candidate_dir / kind / f"{name}.candidate.md"


def _plan_target_label(plan: dict[str, Any] | EvolutionPlan) -> str:
    if isinstance(plan, EvolutionPlan):
        change_request = dict(plan.change_request)
    else:
        change_request = dict(plan.get("change_request", {}))
    if change_request.get("preferred_path"):
        return str(change_request["preferred_path"])
    if change_request.get("target_memory"):
        return str(change_request["target_memory"])
    if change_request.get("bundle_name"):
        return f"bundle:{change_request['bundle_name']}"
    target_files = list(change_request.get("target_files", []) or [])
    if target_files:
        return str(target_files[0])
    return "unknown"


def _plan_bundle_name(plan: dict[str, Any] | EvolutionPlan) -> str | None:
    if isinstance(plan, EvolutionPlan):
        change_request = dict(plan.change_request)
    else:
        change_request = dict(plan.get("change_request", {}))
    bundle_name = change_request.get("bundle_name")
    return str(bundle_name) if bundle_name else None


def _merge_text_artifact_update(original: str, plan: EvolutionPlan) -> str:
    updates = list(plan.change_request.get("proposed_updates", []))
    lines = [original.rstrip(), "", "## Evo Harness Update", ""]
    for item in updates:
        lines.append(f"- {item}")
    lines.extend(["", "## Validation Notes", ""])
    for step in plan.proposal.validator_steps:
        lines.append(f"- {step}")
    return "\n".join(lines).rstrip() + "\n"


def _run_validation_steps(
    plan: EvolutionPlan,
    workspace: Path,
    *,
    run_validation: bool,
) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    for step in plan.proposal.validator_steps:
        if step.startswith("Run regression validation: "):
            command = step.split(": ", 1)[1]
            if not run_validation:
                results.append(
                    ValidationResult(
                        step=step,
                        success=True,
                        output="Skipped command execution.",
                        executed=False,
                    )
                )
                continue
            completed = subprocess.run(
                command,
                cwd=str(workspace),
                shell=True,
                check=False,
                capture_output=True,
                text=True,
            )
            output = "\n".join(part for part in [completed.stdout.strip(), completed.stderr.strip()] if part)
            results.append(
                ValidationResult(
                    step=step,
                    success=completed.returncode == 0,
                    output=output or "(no output)",
                )
            )
            continue
        results.append(ValidationResult(step=step, success=True, output="Validation step recorded."))
    return results


def _promotion_decision(
    validation: list[ValidationResult],
    *,
    plan: EvolutionPlan,
    allow_unvalidated_promotion: bool,
    workspace: Path,
    policy,
) -> tuple[str, PromotionAssessment]:
    score, reasons = _promotion_score(
        validation,
        plan=plan,
        workspace=workspace,
        policy=policy,
    )
    if any(not item.success for item in validation):
        return "reject", PromotionAssessment(score=score, decision="reject", reasons=reasons + ["validation_failed"])
    requires_command = any(step.step.startswith("Run regression validation: ") for step in validation)
    executed_command = any(step.step.startswith("Run regression validation: ") and step.executed for step in validation)
    if requires_command and not executed_command and policy.require_executed_regression and not allow_unvalidated_promotion:
        return "blocked", PromotionAssessment(score=score, decision="blocked", reasons=reasons + ["regression_not_executed"])
    executed_validation_count = sum(1 for step in validation if step.executed)
    if executed_validation_count < policy.min_executed_validations and not allow_unvalidated_promotion:
        return "blocked", PromotionAssessment(score=score, decision="blocked", reasons=reasons + ["not_enough_executed_validations"])
    target = _plan_target_label(plan)
    recent_failures = _recent_failed_promotions(workspace, target=target)
    if recent_failures > policy.max_recent_failed_promotions:
        return "blocked", PromotionAssessment(score=score, decision="blocked", reasons=reasons + ["too_many_recent_failures"])
    if score < policy.min_promotion_score and not allow_unvalidated_promotion:
        return "blocked", PromotionAssessment(score=score, decision="blocked", reasons=reasons + ["score_below_threshold"])
    if policy.cooldown_seconds and _within_cooldown(workspace, target=target, cooldown_seconds=policy.cooldown_seconds):
        return "blocked", PromotionAssessment(score=score, decision="blocked", reasons=reasons + ["cooldown_active"])
    return "promote", PromotionAssessment(score=score, decision="promote", reasons=reasons)


def _restore_target_from_backup(backup: Path, applied_paths: list[Path]) -> Path | None:
    for candidate in applied_paths:
        if candidate.name == backup.name:
            return candidate
    return None


def _restore_backups(backup_paths: list[str], applied_paths: list[str]) -> None:
    for backup in [Path(path) for path in backup_paths]:
        if not backup.exists():
            continue
        target = _restore_target_from_backup(backup, [Path(path) for path in applied_paths])
        if target is None:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, target)


def _recent_failed_promotions(workspace: Path, *, target: str | None = None, limit: int = 20) -> int:
    failures = 0
    for path in list_execution_records(workspace)[:limit]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        execution = payload.get("execution", {})
        plan = payload.get("plan", {})
        state = execution.get("promotion_state")
        success = execution.get("success")
        record_target = _plan_target_label(plan)
        if target and record_target != target:
            continue
        if state in {"blocked", "rejected", "rolled_back"} or success is False:
            failures += 1
    return failures


def _within_cooldown(workspace: Path, *, target: str, cooldown_seconds: int) -> bool:
    records = list_execution_records(workspace)
    if not records:
        return False
    try:
        payload = json.loads(records[0].read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    plan = payload.get("plan", {})
    record_target = _plan_target_label(plan)
    if record_target != target:
        return False
    timestamp_text = records[0].stem.split(".")[0]
    try:
        record_time = datetime.strptime(timestamp_text, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - record_time).total_seconds() < cooldown_seconds


def _promotion_score(
    validation: list[ValidationResult],
    *,
    plan: EvolutionPlan,
    workspace: Path,
    policy,
) -> tuple[float, list[str]]:
    score = 1.0
    reasons: list[str] = []
    if plan.trace.outcome.value == "failure":
        score -= 0.15
        reasons.append("failure_origin")
    if "tool_misuse" in plan.trace.error_tags:
        score -= 0.10
        reasons.append("tool_misuse")
    if "command_policy_violation" in plan.trace.error_tags:
        score -= 0.10
        reasons.append("command_policy_violation")
    if "safety_block" in plan.trace.error_tags:
        score -= 0.08
        reasons.append("safety_block")
    risk_score = float(plan.report.risk_score)
    score -= min(risk_score * 0.25, 0.25)
    reasons.append(f"risk:{risk_score:.2f}")
    executed_validation_count = sum(1 for step in validation if step.executed)
    if executed_validation_count >= policy.min_executed_validations:
        score += 0.10
        reasons.append("executed_validations")
    if any(not item.success for item in validation):
        score -= 0.25
        reasons.append("validation_failed")
    target = _plan_target_label(plan)
    recent_failures = _recent_failed_promotions(workspace, target=target)
    if recent_failures:
        score -= min(0.05 * recent_failures, 0.20)
        reasons.append(f"recent_failures:{recent_failures}")
    return max(0.0, min(score, 1.0)), reasons
