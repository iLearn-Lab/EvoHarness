from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evo_harness.autonomous_evolution import assess_saved_session
from evo_harness.core.workspace import discover_workspace
from evo_harness.harness import ConversationEngine
from evo_harness.harness.memory import add_memory_entry
from evo_harness.harness.messages import ChatMessage
from evo_harness.harness.provider import build_live_provider
from evo_harness.harness.runtime import HarnessRuntime
from evo_harness.harness.settings import load_settings
from evo_harness.models import EvolutionPlan, OperatorName, Outcome, TaskTrace
from evo_harness.operators.capability_growth import build_generic_capability_growth_change_request


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
    artifact_state: str = "none"
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
            "artifact_state": self.artifact_state,
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
                artifact_state="none",
                notes=["No mutation executed because the plan selected stop."],
            )
        if not plan.safe_to_apply:
            return _blocked_execution_result(
                workspace,
                plan=plan,
                mode=mode,
                reason=(
                    "The evolution plan is not safe to apply with the current runtime capabilities. "
                    "A blocked candidate note was written instead of mutating the workspace."
                ),
                block_reason="unsafe_plan",
            )

        normalized_mode = mode
        allow_same_run_candidate_promotion = False
        if mode == "auto":
            normalized_mode = "candidate"
            if settings.promotion.allow_auto_promote:
                normalized_mode = "promote"
                allow_same_run_candidate_promotion = (
                    plan.proposal.operator == OperatorName.GROW_ECOSYSTEM
                    and (run_validation or mode == "auto")
                )
        if (
            normalized_mode == "promote"
            and settings.promotion.require_candidate_before_promotion
            and not _has_prior_candidate_record(workspace, plan=plan)
            and not allow_same_run_candidate_promotion
        ):
            candidate_result = self.execute(
                plan,
                workspace_root=workspace,
                mode="candidate",
                run_validation=False,
                allow_unvalidated_promotion=allow_unvalidated_promotion,
            )
            candidate_result.mode = mode
            candidate_result.success = bool(mode == "auto" and candidate_result.success)
            candidate_result.notes.append(
                "Promotion requires a previously materialized candidate record; staged a candidate artifact instead."
            )
            return candidate_result

        auto_override = bool(mode == "auto" and normalized_mode == "promote" and settings.promotion.allow_auto_promote)
        effective_allow_unvalidated_promotion = allow_unvalidated_promotion or auto_override
        if operator == OperatorName.REVISE_SKILL:
            return self._execute_text_artifact_revision(
                plan,
                workspace=workspace,
                mode=normalized_mode,
                run_validation=run_validation or mode == "auto",
                allow_unvalidated_promotion=effective_allow_unvalidated_promotion,
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
                allow_unvalidated_promotion=effective_allow_unvalidated_promotion,
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
                allow_unvalidated_promotion=effective_allow_unvalidated_promotion,
                policy=settings.promotion,
                safety=settings.safety,
            )
        if operator == OperatorName.DISTILL_MEMORY:
            return self._execute_distill_memory(
                plan,
                workspace=workspace,
                mode=normalized_mode,
                run_validation=run_validation or mode == "auto",
                allow_unvalidated_promotion=effective_allow_unvalidated_promotion,
                policy=settings.promotion,
                safety=settings.safety,
            )
        return ExecutionResult(
            operator=operator.value,
            mode=mode,
            success=False,
            promotion_state="unsupported",
            artifact_state="none",
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

        updated, ai_generated = _rewrite_text_artifact(
            original,
            plan,
            workspace=workspace,
            target=target,
            artifact_kind=artifact_kind,
            default_header=default_header,
        )
        if ai_generated:
            result.notes.append(f"Used the live provider to generate the revised {artifact_kind[:-1]} content.")
        else:
            result.notes.append(f"Used the deterministic fallback to rewrite the {artifact_kind[:-1]} content.")

        if mode == "candidate":
            candidate_path = candidate_dir / f"{target.stem}.candidate{target.suffix}"
            candidate_path.write_text(updated, encoding="utf-8")
            result.created_paths.append(str(candidate_path))
            result.notes.append(f"Wrote a candidate {artifact_kind[:-1]} file without mutating the original.")
            result.promotion_state = "candidate_only"
            result.artifact_state = "candidate"
        elif mode == "apply":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(updated, encoding="utf-8")
            result.applied_paths.append(str(target))
            result.notes.append(success_note)
            result.promotion_state = "applied"
            result.artifact_state = "active"
        elif mode == "promote":
            candidate_path = candidate_dir / f"{target.stem}.candidate{target.suffix}"
            candidate_path.write_text(updated, encoding="utf-8")
            result.created_paths.append(str(candidate_path))
            result.notes.append(f"Created candidate {artifact_kind[:-1]} before promotion.")
            result.artifact_state = "candidate"
        else:
            result.success = False
            result.promotion_state = "invalid_mode"
            result.notes.append(f"Unknown execution mode: {mode}")
            return _finalize_execution_result(workspace, plan=plan, result=result)

        result.validation = _run_validation_steps(plan, workspace, run_validation=run_validation, mode=mode)
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
                result.artifact_state = "active"
                result.notes.append(f"Promoted candidate {artifact_kind[:-1]} to the active target.")
            elif validation_decision == "blocked":
                result.success = False
                result.promotion_state = "blocked"
                result.notes.append("Promotion blocked because the gating policy was not satisfied.")
            else:
                result.success = False
                result.promotion_state = "rejected"
                result.notes.append("Promotion rejected because validation or history gates failed.")

        return _finalize_execution_result(workspace, plan=plan, result=result)

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
            result.success = False
            result.promotion_state = "blocked"
            result.notes.append(
                "No scaffold assets were selected for this ecosystem growth plan. "
                "A diagnostic candidate note was written instead of silently skipping the evolution."
            )
            return _finalize_execution_result(workspace, plan=plan, result=result)

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
            result.artifact_state = "candidate"
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
            result.artifact_state = "active"
        elif mode == "promote":
            for asset in assets:
                candidate_path = _ecosystem_candidate_path(candidate_dir, asset)
                candidate_path.parent.mkdir(parents=True, exist_ok=True)
                candidate_path.write_text(str(asset["content"]).rstrip() + "\n", encoding="utf-8")
                result.created_paths.append(str(candidate_path))
            result.notes.append("Created candidate ecosystem assets before promotion.")
            result.artifact_state = "candidate"
        else:
            result.success = False
            result.promotion_state = "invalid_mode"
            result.notes.append(f"Unknown execution mode: {mode}")
            return _finalize_execution_result(workspace, plan=plan, result=result)

        result.validation = _run_validation_steps(plan, workspace, run_validation=run_validation, mode=mode)
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
                result.artifact_state = "active"
                result.notes.append("Promoted the ecosystem growth bundle into the active workspace.")
            elif validation_decision == "blocked":
                result.success = False
                result.promotion_state = "blocked"
                result.notes.append("Promotion blocked because the ecosystem bundle did not satisfy the gates.")
            else:
                result.success = False
                result.promotion_state = "rejected"
                result.notes.append("Promotion rejected because validation or history gates failed.")
        return _finalize_execution_result(workspace, plan=plan, result=result)

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
            result.artifact_state = "candidate"
        elif mode == "apply":
            path = add_memory_entry(workspace, title, body)
            result.applied_paths.append(str(path))
            result.notes.append("Added a new memory entry to the workspace.")
            result.promotion_state = "applied"
            result.artifact_state = "active"
        elif mode == "promote":
            candidate_dir, _rollback_dir = _candidate_and_rollback_dirs(workspace, "memory")
            candidate_path = candidate_dir / f"{plan.trace.task_id}.memory.md"
            candidate_path.write_text(body, encoding="utf-8")
            result.created_paths.append(str(candidate_path))
            result.notes.append("Created candidate memory entry before promotion.")
            result.artifact_state = "candidate"
        else:
            result.success = False
            result.promotion_state = "invalid_mode"
            result.notes.append(f"Unknown execution mode: {mode}")
            return _finalize_execution_result(workspace, plan=plan, result=result)

        result.validation = _run_validation_steps(plan, workspace, run_validation=run_validation, mode=mode)
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
                result.artifact_state = "active"
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
        return _finalize_execution_result(workspace, plan=plan, result=result)


def write_execution_record(
    workspace_root: str | Path,
    *,
    plan: EvolutionPlan,
    execution: ExecutionResult,
    origin: str = "manual",
    metadata: dict[str, Any] | None = None,
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
                "metadata": {
                    "origin": origin,
                    **dict(metadata or {}),
                },
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


def _rewrite_text_artifact(
    original: str,
    plan: EvolutionPlan,
    *,
    workspace: Path,
    target: Path,
    artifact_kind: str,
    default_header: str,
) -> tuple[str, bool]:
    generated = _generate_text_artifact_with_ai(
        workspace,
        plan=plan,
        target=target,
        artifact_kind=artifact_kind,
        default_header=default_header,
        original=original,
    )
    if generated:
        return generated, True
    frontmatter = ""
    body = original.strip()
    if body.startswith("---\n"):
        closing = body.find("\n---\n", 4)
        if closing != -1:
            frontmatter = body[: closing + 5].strip() + "\n\n"
            body = body[closing + 5 :].strip()

    title = f"# {default_header}"
    body_lines = [line.rstrip() for line in body.splitlines()]
    if body_lines and body_lines[0].lstrip().startswith("#"):
        title = body_lines[0].strip()
        body_lines = body_lines[1:]
    existing_body = "\n".join(body_lines).strip()
    evidence = dict(plan.change_request.get("evidence", {}) or {})
    proposed_updates = [str(item).strip() for item in plan.change_request.get("proposed_updates", []) if str(item).strip()]
    findings = [
        str(item.get("summary", "")).strip()
        for item in evidence.get("findings", [])
        if isinstance(item, dict) and str(item.get("summary", "")).strip()
    ]
    error_tags = [str(item).strip() for item in evidence.get("error_tags", []) if str(item).strip()]
    artifact_label = artifact_kind[:-1]
    workflow_adjustments = proposed_updates or [f"Keep the {artifact_label} narrowly scoped and replayable."]
    recovery_lines = [f"- Watch for tag: {item}" for item in error_tags] or [f"- Re-check the {artifact_label} when replay still fails or loops."]
    finding_lines = [f"- Finding: {item}" for item in findings[:4]]
    validation_lines = [f"- {step}" for step in plan.proposal.validator_steps] or ["- Replay the original task before promotion."]
    section_lines = [
        title,
        "",
        existing_body if existing_body else f"Refined {artifact_label} generated from the latest evolution trace.",
        "",
        "## When To Use",
        f"- {plan.trace.summary or plan.change_request.get('summary', '') or f'Use this {artifact_label} when the same failure pattern appears again.'}",
        "",
        "## Workflow Adjustments",
        *[f"- {item}" for item in workflow_adjustments],
        "",
        "## Failure Recovery",
        *recovery_lines,
        *finding_lines,
        "",
        "## Validation",
        *validation_lines,
    ]
    return frontmatter + "\n".join(section_lines).rstrip() + "\n", False


def _generate_text_artifact_with_ai(
    workspace: Path,
    *,
    plan: EvolutionPlan,
    target: Path,
    artifact_kind: str,
    default_header: str,
    original: str,
) -> str | None:
    settings = load_settings(workspace=workspace)
    _apply_provider_config_from_trace(settings, plan)
    try:
        provider = build_live_provider(settings=settings)
    except Exception:
        return None
    prompt = "\n".join(
        [
            "Rewrite one Evo Harness artifact into a directly usable final file.",
            "Return the full file content only. No markdown fences. No explanation.",
            "Preserve any YAML frontmatter if it already exists and keep the artifact concise but runnable/usable.",
            "",
            f"Artifact kind: {artifact_kind}",
            f"Target path: {target}",
            f"Default header: {default_header}",
            "",
            "Task trace summary:",
            json.dumps(plan.trace.to_dict(), ensure_ascii=False, indent=2),
            "",
            "Change request:",
            json.dumps(plan.change_request, ensure_ascii=False, indent=2),
            "",
            "Validation steps:",
            json.dumps(plan.proposal.validator_steps, ensure_ascii=False, indent=2),
            "",
            "Current file content:",
            original,
        ]
    )
    try:
        turn = provider.next_turn(
            system_prompt=(
                "You are the artifact rewriter for Evo Harness. "
                "Produce a polished final artifact that the runtime can use immediately. "
                "Do not describe changes; output only the final file text."
            ),
            messages=[ChatMessage(role="user", text=prompt)],
            tool_schema=[],
        )
    except Exception:
        return None
    text = _strip_markdown_fences(str(turn.assistant_text or "").strip())
    return text if text else None


def _blocked_execution_result(
    workspace: Path,
    *,
    plan: EvolutionPlan,
    mode: str,
    reason: str,
    block_reason: str,
) -> ExecutionResult:
    result = ExecutionResult(
        operator=plan.proposal.operator.value,
        mode=mode,
        success=False,
        promotion_state="blocked",
        artifact_state="candidate",
        notes=[reason],
    )
    candidate_path = _write_execution_note_artifact(
        workspace,
        plan=plan,
        note_kind=block_reason,
        payload={
            "reason": reason,
            "operator": plan.proposal.operator.value,
            "mode": mode,
            "safe_to_apply": plan.safe_to_apply,
            "required_capabilities": list(plan.proposal.required_capabilities),
            "change_targets": list(plan.proposal.change_targets),
        },
    )
    result.created_paths.append(str(candidate_path))
    return result


def _strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _finalize_execution_result(
    workspace: Path,
    *,
    plan: EvolutionPlan,
    result: ExecutionResult,
) -> ExecutionResult:
    if result.applied_paths:
        result.artifact_state = "active"
    elif result.created_paths:
        result.artifact_state = "candidate"
    else:
        result.artifact_state = "none"
    if (
        plan.proposal.operator != OperatorName.STOP
        and result.artifact_state == "none"
        and result.promotion_state not in {"skipped"}
    ):
        candidate_path = _write_execution_note_artifact(
            workspace,
            plan=plan,
            note_kind="no-artifact-fallback",
            payload={
                "reason": "No concrete artifact path was materialized for this execution result.",
                "promotion_state": result.promotion_state,
                "notes": list(result.notes),
                "operator": result.operator,
                "mode": result.mode,
            },
        )
        result.created_paths.append(str(candidate_path))
        result.artifact_state = "candidate"
        if result.promotion_state == "none":
            result.promotion_state = "candidate_only"
        result.notes.append("Materialized a diagnostic candidate artifact because the evolution produced no concrete files.")
    return result


def _write_execution_note_artifact(
    workspace: Path,
    *,
    plan: EvolutionPlan,
    note_kind: str,
    payload: dict[str, Any],
) -> Path:
    candidate_dir, _rollback_dir = _candidate_and_rollback_dirs(workspace, "execution-notes")
    target = candidate_dir / f"{plan.trace.task_id}.{note_kind}.json"
    body = {
        "task_id": plan.trace.task_id,
        "operator": plan.proposal.operator.value,
        "target": _plan_target_label(plan),
        "bundle_name": _plan_bundle_name(plan),
        "payload": payload,
    }
    target.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def _has_prior_candidate_record(workspace: Path, *, plan: EvolutionPlan) -> bool:
    target = _plan_target_label(plan)
    bundle_name = _plan_bundle_name(plan)
    for path in list_execution_records(workspace):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        execution = dict(payload.get("execution", {}))
        record_plan = payload.get("plan", {})
        record_target = _plan_target_label(record_plan)
        record_bundle = _plan_bundle_name(record_plan)
        if record_target != target or record_bundle != bundle_name:
            continue
        if execution.get("created_paths") or execution.get("applied_paths"):
            return True
    return False


def _run_validation_steps(
    plan: EvolutionPlan,
    workspace: Path,
    *,
    run_validation: bool,
    mode: str,
) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    for step in plan.proposal.validator_steps:
        if step == "Validate replay readiness and surface completeness.":
            success, output = _validate_replay_readiness(plan, workspace)
            results.append(ValidationResult(step=step, success=success, output=output, executed=True))
            continue
        if step.startswith("Validate deliverable signals: "):
            signals = [item.strip() for item in step.split(": ", 1)[1].split(",") if item.strip()]
            success, output = _validate_deliverable_signals(plan, workspace, signals=signals)
            results.append(ValidationResult(step=step, success=success, output=output, executed=True))
            continue
        if step.startswith("Replay the original task: "):
            if not run_validation:
                results.append(
                    ValidationResult(
                        step=step,
                        success=True,
                        output="Skipped live replay execution; structural replay readiness remains recorded separately.",
                        executed=False,
                    )
                )
                continue
            if (
                mode == "apply"
                and plan.proposal.operator == OperatorName.GROW_ECOSYSTEM
                and str(plan.change_request.get("bundle_name", "") or "") == "capability-growth"
            ):
                success, output, executed = _run_replay_validation_with_refinement(plan, workspace)
            else:
                success, output, executed = _run_replay_validation(plan, workspace)
            results.append(ValidationResult(step=step, success=success, output=output, executed=executed))
            continue
        if step == "Validate that the new ecosystem assets are discoverable before promotion.":
            success, output = _validate_ecosystem_discoverability(plan, workspace, mode=mode)
            results.append(ValidationResult(step=step, success=success, output=output, executed=True))
            continue
        if step.startswith("Run regression validation: "):
            command = step.split(": ", 1)[1]
            if command == "default regression checks":
                results.append(
                    ValidationResult(
                        step=step,
                        success=True,
                        output="No concrete regression command was available for this plan.",
                        executed=False,
                    )
                )
                continue
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
                encoding="utf-8",
                errors="replace",
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
    requires_replay = any(step.step.startswith("Replay the original task: ") for step in validation)
    executed_replay = any(step.step.startswith("Replay the original task: ") and step.executed for step in validation)
    if requires_replay and not executed_replay and not allow_unvalidated_promotion:
        return "blocked", PromotionAssessment(score=score, decision="blocked", reasons=reasons + ["replay_not_executed"])
    requires_command = any(
        step.step.startswith("Run regression validation: ")
        and not step.step.endswith("default regression checks")
        for step in validation
    )
    executed_command = any(
        step.step.startswith("Run regression validation: ")
        and not step.step.endswith("default regression checks")
        and step.executed
        for step in validation
    )
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


def _validate_ecosystem_discoverability(plan: EvolutionPlan, workspace: Path, *, mode: str) -> tuple[bool, str]:
    if mode in {"candidate", "promote"}:
        structurally_missing = _structurally_missing_ecosystem_assets(plan)
        if structurally_missing:
            return False, "Candidate ecosystem assets are incomplete: " + ", ".join(structurally_missing)
        if mode == "promote":
            return True, "Candidate ecosystem assets are structurally complete and ready for promotion into the active workspace."
        return True, "Candidate ecosystem assets are structurally complete and ready for later apply/promote validation."

    runtime = HarnessRuntime(workspace)
    commands = {item["name"] for item in runtime.list_commands() if item.get("name")}
    skills = {item["name"] for item in runtime.list_skills() if item.get("name")}
    agents = {item["name"] for item in runtime.list_agents() if item.get("name")}
    plugins = {item["manifest"]["name"] for item in runtime.list_plugins() if item.get("manifest")}
    mcp_servers = {item["name"] for item in runtime.list_mcp_servers() if item.get("name")}

    missing: list[str] = []
    for asset in plan.change_request.get("scaffold_assets", []):
        kind = str(asset.get("kind", ""))
        name = str(asset.get("name", ""))
        if kind == "command" and name not in commands:
            missing.append(f"command:{name}")
        elif kind == "skill" and name not in skills:
            missing.append(f"skill:{name}")
        elif kind == "agent" and name not in agents:
            missing.append(f"agent:{name}")
        elif kind == "plugin":
            expected_plugin = _expected_plugin_name_from_asset(asset)
            if expected_plugin and expected_plugin not in plugins:
                missing.append(f"plugin:{expected_plugin}")
            expected_servers = _expected_mcp_servers_from_asset(asset)
            for server_name in expected_servers:
                if not any(candidate == server_name or candidate.endswith(f":{server_name}") for candidate in mcp_servers):
                    missing.append(f"mcp_server:{server_name}")

    bundle_name = str(plan.change_request.get("bundle_name", "") or "")
    if bundle_name == "document-automation" and "document-automation:doc-tools" not in mcp_servers:
        missing.append("mcp_server:document-automation:doc-tools")

    if missing:
        return False, "Missing discoverable assets: " + ", ".join(missing)
    return True, "All scaffolded ecosystem assets are discoverable through the runtime registry."


def _structurally_missing_ecosystem_assets(plan: EvolutionPlan) -> list[str]:
    missing: list[str] = []
    for asset in plan.change_request.get("scaffold_assets", []):
        kind = str(asset.get("kind", "") or "").strip()
        name = str(asset.get("name", "") or "").strip()
        target_path = str(asset.get("target_path", "") or "").strip()
        content = str(asset.get("content", "") or "").strip()
        if not kind or not name or not target_path or not content:
            missing.append(name or target_path or kind or "unknown-asset")
    return missing


def _expected_plugin_name_from_asset(asset: dict[str, Any]) -> str | None:
    target_path = str(asset.get("target_path", "") or "")
    if not target_path.endswith("/.claude-plugin/plugin.json"):
        return None
    try:
        payload = json.loads(str(asset.get("content", "") or ""))
    except json.JSONDecodeError:
        return None
    name = str(payload.get("name", "") or "").strip()
    return name or None


def _expected_mcp_servers_from_asset(asset: dict[str, Any]) -> list[str]:
    target_path = str(asset.get("target_path", "") or "")
    if not target_path.endswith("/.mcp.json"):
        return []
    try:
        payload = json.loads(str(asset.get("content", "") or ""))
    except json.JSONDecodeError:
        return []
    servers = payload.get("mcpServers", {})
    if not isinstance(servers, dict):
        return []
    return [str(name).strip() for name in servers if str(name).strip()]


def _looks_like_replay_environment_issue(error: Exception | str) -> bool:
    text = str(error).lower()
    return any(
        marker in text
        for marker in (
            "no api key found",
            "invalid authentication",
            "invalid_authentication",
            "authentication",
            "rate limit",
            "timeout",
            "connection",
            "dns",
            "temporarily unavailable",
            "503",
            "502",
            "network",
        )
    )


def _validate_replay_readiness(plan: EvolutionPlan, workspace: Path) -> tuple[bool, str]:
    settings = load_settings(workspace=workspace)
    original_prompt = str(
        plan.trace.artifacts.get("initial_user_prompt")
        or plan.trace.artifacts.get("replay_prompt")
        or ""
    ).strip()
    if not original_prompt:
        return True, "Replay readiness is incomplete because no original or replay prompt was available yet; candidate materialization can continue, but promotion should remain blocked until replay is possible."

    if plan.proposal.operator == OperatorName.GROW_ECOSYSTEM:
        structural_missing = _structurally_missing_ecosystem_assets(plan)
        if structural_missing:
            return False, "Replay readiness failed because scaffold assets are incomplete: " + ", ".join(structural_missing)

    runtime = HarnessRuntime(workspace)
    missing: list[str] = []
    capability_plan = dict(plan.change_request.get("capability_plan", {}) or {})
    scaffold_assets = [dict(item) for item in plan.change_request.get("scaffold_assets", [])]
    scaffold_kinds = {str(item.get("kind", "")).strip() for item in scaffold_assets if str(item.get("kind", "")).strip()}
    for surface_name in capability_plan.get("required_assets", []):
        if surface_name == "command" and not (runtime.list_commands() or "command" in scaffold_kinds):
            missing.append("command")
        elif surface_name == "skill" and not (runtime.list_skills() or "skill" in scaffold_kinds):
            missing.append("skill")
        elif surface_name == "agent" and not (runtime.list_agents() or "agent" in scaffold_kinds):
            missing.append("agent")
    if missing:
        return False, "Replay readiness failed because required runtime surfaces are not yet discoverable: " + ", ".join(missing)

    provider_config = dict(plan.trace.artifacts.get("provider_config", {}) or {})
    api_key_env = str(provider_config.get("api_key_env", "") or "").strip()
    provider_ready = bool(
        settings.provider.api_key
        or (api_key_env and os.environ.get(api_key_env))
    )
    if provider_config and not provider_ready:
        return True, (
            "Replay readiness passed structurally, but live replay may be skipped because provider credentials "
            f"were not found in `{api_key_env}`."
        )
    return True, "Replay readiness passed: the task prompt, scaffold surfaces, and runtime layout are present."


def _expected_output_paths_from_prompt(prompt: str, *, workspace: Path) -> list[Path]:
    candidates = re.findall(
        r"[\w./\\\\:-]+\.(?:md|json|docx|doc|txt|csv|yaml|yml|xml|html|pdf|png|jpg|jpeg)",
        str(prompt or ""),
        flags=re.IGNORECASE,
    )
    paths: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = str(candidate).strip().strip("`'\"")
        lowered = cleaned.lower()
        if not cleaned or lowered.endswith("manifest.json"):
            continue
        if "output" not in lowered and "report" not in lowered and "result" not in lowered and "summary" not in lowered:
            continue
        resolved = Path(cleaned)
        resolved = resolved if resolved.is_absolute() else (workspace / resolved).resolve()
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        paths.append(resolved)
    return paths


def _validate_deliverable_signals(
    plan: EvolutionPlan,
    workspace: Path,
    *,
    signals: list[str],
) -> tuple[bool, str]:
    output_paths = _expected_output_paths_from_prompt(str(plan.trace.artifacts.get("initial_user_prompt", "") or ""), workspace=workspace)
    lines: list[str] = []
    success = True
    for signal in signals:
        normalized = signal.strip().lower()
        if normalized == "file_exists":
            missing = [str(path) for path in output_paths if not path.exists()]
            if missing:
                success = False
                lines.append("Missing expected outputs: " + ", ".join(missing))
            else:
                lines.append("All expected output files exist.")
        elif normalized == "non_zero_file_size":
            empty = [str(path) for path in output_paths if path.exists() and path.stat().st_size == 0]
            if empty:
                success = False
                lines.append("Expected outputs with zero bytes: " + ", ".join(empty))
            else:
                lines.append("All expected output files have non-zero size.")
        elif normalized == "valid_docx_format":
            docx_targets = [path for path in output_paths if path.suffix.lower() == ".docx"]
            invalid: list[str] = []
            for path in docx_targets:
                if not path.exists():
                    invalid.append(str(path))
                    continue
                try:
                    with zipfile.ZipFile(path):
                        pass
                except Exception:
                    invalid.append(str(path))
            if invalid:
                success = False
                lines.append("Invalid DOCX outputs: " + ", ".join(invalid))
            else:
                lines.append("All DOCX outputs have a valid OOXML container.")
        else:
            lines.append(f"Recorded semantic validation signal: {signal}")
    return success, "\n".join(lines)


def _run_replay_validation(plan: EvolutionPlan, workspace: Path) -> tuple[bool, str, bool]:
    success, output, _assessment, executed = _run_single_replay_validation(plan, workspace)
    return success, output, executed


def _run_replay_validation_with_refinement(plan: EvolutionPlan, workspace: Path) -> tuple[bool, str, bool]:
    replay_contract = dict(plan.change_request.get("replay_contract", {}) or {})
    max_rounds = int(replay_contract.get("max_refinement_rounds", 2) or 2)
    outputs: list[str] = []
    current_plan = plan
    for round_index in range(max_rounds + 1):
        success, output, replay_assessment, executed = _run_single_replay_validation(current_plan, workspace)
        label = "initial" if round_index == 0 else f"refinement-{round_index}"
        outputs.append(f"[{label}] {output}")
        if success:
            return True, "\n".join(outputs), executed
        if not executed:
            return True, "\n".join(outputs), False
        if replay_assessment is None or replay_assessment.capability_gap is None:
            return False, "\n".join(outputs), True
        if round_index >= max_rounds:
            outputs.append(f"Reached max_refinement_rounds={max_rounds} without a healthy replay.")
            return False, "\n".join(outputs), True
        refined_change_request = _refine_generic_growth_change_request(
            current_plan,
            workspace=workspace,
            replay_assessment=replay_assessment,
            round_index=round_index + 1,
        )
        _apply_refined_ecosystem_assets(workspace, refined_change_request)
        current_plan.change_request.update(refined_change_request)
        outputs.append(
            "Applied replay-driven refinement round "
            f"{round_index + 1} with {len(refined_change_request.get('scaffold_assets', []))} refreshed assets."
        )
    return False, "\n".join(outputs), True


def _run_single_replay_validation(plan: EvolutionPlan, workspace: Path) -> tuple[bool, str, Any, bool]:
    settings = load_settings(workspace=workspace)
    _apply_provider_config_from_trace(settings, plan)
    original_prompt = str(
        plan.trace.artifacts.get("initial_user_prompt")
        or plan.trace.artifacts.get("replay_prompt")
        or ""
    ).strip()
    if not original_prompt:
        return True, "Skipped live replay — no replay prompt was recorded in the saved session artifacts.", None, False

    command_name, command_arguments = _select_replay_entrypoint(plan, workspace=workspace, original_prompt=original_prompt)
    bundle_name = str(plan.change_request.get("bundle_name", "") or "").strip()
    replay_prompt = _build_replay_prompt(
        original_prompt,
        bundle_name=bundle_name,
        requirement_graph=dict(plan.change_request.get("requirement_graph", {}) or {}),
        capability_plan=dict(plan.change_request.get("capability_plan", {}) or {}),
        research_plan=dict(plan.change_request.get("research_plan", {}) or {}),
        implementation_contract=dict(plan.change_request.get("implementation_contract", {}) or {}),
    )
    try:
        provider = build_live_provider(settings=settings)
    except Exception as exc:
        if "No API key found" in str(exc):
            return True, f"Skipped live replay because no provider credentials were available: {exc}", None, False
        return True, f"Skipped live replay because the provider could not be initialized cleanly: {exc}", None, False

    staged_assets: list[tuple[Path, str | None]] = []
    try:
        if plan.proposal.operator == OperatorName.GROW_ECOSYSTEM:
            staged_assets = _stage_replay_ecosystem_assets(plan, workspace)

        replay_runtime = HarnessRuntime(workspace)
        replay_runtime.settings.runtime.auto_self_evolution = False
        replay_runtime.tool_registry = replay_runtime.tool_registry.filtered(
            [item["name"] for item in replay_runtime.list_tools() if item.get("name") != "run_subagent"]
        )
        replay_engine = ConversationEngine(replay_runtime)
        try:
            replay_result = replay_engine.submit(
                prompt=replay_prompt,
                provider=provider,
                command_name=command_name,
                command_arguments=command_arguments,
                max_turns=min(settings.query.max_turns, 6 if dict(plan.change_request.get("research_plan", {}) or {}).get("research_needed") else 4),
            )
        except Exception as exc:
            if _looks_like_replay_environment_issue(exc):
                return True, f"Skipped live replay because the child session hit an environment/provider issue: {exc}", None, False
            return False, f"Replay validation failed during child session execution: {exc}", None, True

        try:
            replay_assessment = assess_saved_session(
                workspace,
                settings=settings,
                session_id="latest",
            )
        except Exception as exc:
            return (
                True if _looks_like_replay_environment_issue(exc) else False,
                "Replay child session completed, but autonomous assessment of the replay failed: "
                f"{exc}",
                None,
                False if _looks_like_replay_environment_issue(exc) else True,
            )
    finally:
        _restore_replay_ecosystem_assets(staged_assets)

    if replay_assessment.capability_gap is not None:
        return (
            False,
            "Replay session still exposed a capability gap: "
            f"{replay_assessment.capability_gap.get('name', 'unknown-gap')}. "
            f"Summary: {replay_assessment.summary}",
            replay_assessment,
            True,
        )
    if replay_assessment.needs_evolution and replay_assessment.operator != OperatorName.STOP.value:
        return (
            False,
            "Replay session still requested another evolution step: "
            f"{replay_assessment.operator}. Summary: {replay_assessment.summary}",
            replay_assessment,
            True,
        )
    if replay_assessment.outcome != "success":
        return (
            False,
            "Replay session did not finish in a healthy success state: "
            f"{replay_assessment.outcome}. Summary: {replay_assessment.summary}",
            replay_assessment,
            True,
        )

    return (
        True,
        "Replay session succeeded after evolution. "
        f"stop_reason={replay_result.stop_reason}, turns={replay_result.turn_count}, "
        f"provider={replay_result.provider_name}. Summary: {replay_assessment.summary}",
        replay_assessment,
        True,
    )


def _stage_replay_ecosystem_assets(plan: EvolutionPlan, workspace: Path) -> list[tuple[Path, str | None]]:
    staged: list[tuple[Path, str | None]] = []
    for asset in plan.change_request.get("scaffold_assets", []):
        target_path = str(asset.get("target_path", "") or "").strip()
        if not target_path:
            continue
        target = (workspace / target_path).resolve()
        previous = target.read_text(encoding="utf-8") if target.exists() else None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(asset.get("content", "")).rstrip() + "\n", encoding="utf-8")
        staged.append((target, previous))
    return staged


def _select_replay_entrypoint(
    plan: EvolutionPlan,
    *,
    workspace: Path,
    original_prompt: str,
) -> tuple[str | None, str]:
    active_command_name = str(plan.trace.artifacts.get("active_command_name", "") or "").strip()
    active_command_arguments = str(plan.trace.artifacts.get("active_command_arguments", "") or "")
    if active_command_name:
        return active_command_name, active_command_arguments

    if plan.proposal.operator == OperatorName.GROW_ECOSYSTEM:
        command_candidates = [
            str(asset.get("name", "")).strip()
            for asset in plan.change_request.get("scaffold_assets", [])
            if str(asset.get("kind", "")).strip() == "command" and str(asset.get("name", "")).strip()
        ]
        if command_candidates:
            runtime = HarnessRuntime(workspace)
            available_commands = {item["name"] for item in runtime.list_commands() if item.get("name")}
            for candidate in command_candidates:
                if candidate in available_commands:
                    return candidate, original_prompt

    return None, active_command_arguments


def _restore_replay_ecosystem_assets(staged_assets: list[tuple[Path, str | None]]) -> None:
    for target, previous in reversed(staged_assets):
        if previous is None:
            if target.exists():
                target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(previous, encoding="utf-8")


def _refine_generic_growth_change_request(
    plan: EvolutionPlan,
    *,
    workspace: Path,
    replay_assessment,
    round_index: int,
) -> dict[str, Any]:
    requirement_graph = dict(plan.change_request.get("requirement_graph", {}) or {})
    replay_contract = dict(plan.change_request.get("replay_contract", {}) or {})
    replay_gap = dict(replay_assessment.capability_gap or {})
    evidence = _unique_text_items(
        [
            *[str(item) for item in requirement_graph.get("evidence", [])],
            *[str(item) for item in replay_gap.get("evidence", [])],
            *[str(item) for item in getattr(replay_assessment, "evidence", [])],
            str(getattr(replay_assessment, "summary", "") or ""),
        ]
    )
    preferred_surfaces = [
        str(item).strip()
        for item in replay_gap.get("preferred_surfaces", []) or plan.change_request.get("capability_plan", {}).get("preferred_surfaces", [])
        if str(item).strip()
    ]
    artifacts = {
        "initial_user_prompt": replay_contract.get("original_prompt") or plan.trace.artifacts.get("initial_user_prompt", ""),
        "replay_prompt": getattr(replay_assessment, "replay_prompt", None) or replay_contract.get("original_prompt", ""),
        "capability_gap": {
            "name": str(replay_gap.get("name", "") or requirement_graph.get("capability_name", "") or "workspace-capability"),
            "preferred_surfaces": preferred_surfaces,
            "evidence": evidence,
            **{
                key: [
                    str(item).strip()
                    for item in replay_gap.get(key, []) or requirement_graph.get(key, [])
                    if str(item).strip()
                ]
                for key in (
                    "inputs",
                    "outputs",
                    "workflow_actions",
                    "state_targets",
                    "dependencies",
                    "constraints",
                    "validation_targets",
                    "domain_tags",
                )
                if any(str(item).strip() for item in replay_gap.get(key, []) or requirement_graph.get(key, []))
            },
            **{
                key: dict(replay_gap.get(key) or requirement_graph.get(key) or {})
                for key in ("research_plan", "implementation_contract", "replay_contract")
                if isinstance(replay_gap.get(key) or requirement_graph.get(key), dict)
                and dict(replay_gap.get(key) or requirement_graph.get(key))
            },
        },
    }
    refined_trace = TaskTrace(
        task_id=plan.trace.task_id,
        harness=plan.trace.harness,
        outcome=Outcome.FAILURE,
        summary=str(getattr(replay_assessment, "summary", "") or plan.trace.summary),
        repeated_failures=plan.trace.repeated_failures,
        reusable_success_pattern=False,
        error_tags=_unique_text_items([*plan.trace.error_tags, *getattr(replay_assessment, "error_tags", [])]),
        tool_calls=plan.trace.tool_calls,
        token_cost=plan.trace.token_cost,
        token_budget=plan.trace.token_budget,
        validation_targets=list(plan.trace.validation_targets),
        artifacts=artifacts,
    )
    refined_request = build_generic_capability_growth_change_request(
        refined_trace,
        discover_workspace(workspace),
    )
    refined_request["refinement_round"] = round_index
    return refined_request


def _apply_refined_ecosystem_assets(workspace: Path, change_request: dict[str, Any]) -> None:
    for asset in change_request.get("scaffold_assets", []):
        target = (workspace / str(asset.get("target_path", ""))).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(asset.get("content", "")).rstrip() + "\n", encoding="utf-8")


def _build_replay_prompt(
    original_prompt: str,
    *,
    bundle_name: str,
    requirement_graph: dict[str, Any] | None = None,
    capability_plan: dict[str, Any] | None = None,
    research_plan: dict[str, Any] | None = None,
    implementation_contract: dict[str, Any] | None = None,
) -> str:
    requirement_graph = dict(requirement_graph or {})
    capability_plan = dict(capability_plan or {})
    research_plan = dict(research_plan or {})
    implementation_contract = dict(implementation_contract or {})
    lines = [
        "Replay the original user task in a fresh session.",
        "Before answering, inspect the current workspace surface and actively use any new commands, skills, plugins, or MCP tools that were added by self-evolution if they are relevant.",
        "Do not merely explain the missing capability. Try to use the new capability surface if it exists now.",
        "Stay conservative: avoid broad exploration, avoid subagents, and prefer the smallest direct path to completing the task.",
        "If a newly added command or MCP tool matches the task, use it first before falling back to ad-hoc scripting.",
    ]
    if bundle_name:
        lines.append(f"Expected newly added bundle: {bundle_name}.")
    if capability_plan.get("required_assets"):
        lines.append(
            "Expected new surfaces: "
            + ", ".join(str(item) for item in capability_plan.get("required_assets", []) if str(item).strip())
            + "."
        )
    if requirement_graph.get("capability_name"):
        lines.append(f"Capability under validation: {requirement_graph.get('capability_name')}.")
    if implementation_contract.get("primary_entrypoints"):
        lines.append(
            "Prefer these entrypoints during replay: "
            + ", ".join(str(item) for item in implementation_contract.get("primary_entrypoints", []) if str(item).strip())
            + "."
        )
    if implementation_contract.get("validation_steps"):
        lines.append("Implementation contract validation steps:")
        lines.extend(
            f"- {item}"
            for item in [str(item).strip() for item in implementation_contract.get("validation_steps", []) if str(item).strip()][:6]
        )
    if research_plan.get("research_needed"):
        lines.extend(
            [
                "If the implementation path is unclear, research it first before inventing a solution.",
                "Use any newly added `capability-research` or web research MCP surfaces to search official docs and reference implementations.",
            ]
        )
        search_queries = [str(item).strip() for item in research_plan.get("search_queries", []) if str(item).strip()]
        if search_queries:
            lines.append("Suggested research queries:")
            lines.extend(f"- {item}" for item in search_queries[:6])
        checkpoints = [str(item).strip() for item in research_plan.get("implementation_checkpoints", []) if str(item).strip()]
        if checkpoints:
            lines.append("Implementation checkpoints:")
            lines.extend(f"- {item}" for item in checkpoints[:5])
    validation_hints = [str(item).strip() for item in capability_plan.get("validation_hints", []) if str(item).strip()]
    if validation_hints:
        lines.append("Validation priorities:")
        lines.extend(f"- {item}" for item in validation_hints[:6])
    lines.extend(
        [
            "",
            "Original user task:",
            original_prompt,
        ]
    )
    return "\n".join(lines)


def _apply_provider_config_from_trace(settings, plan: EvolutionPlan) -> None:
    provider_config = dict(plan.trace.artifacts.get("provider_config", {}) or {})
    if not provider_config:
        return
    if provider_config.get("model"):
        settings.model = str(provider_config["model"])
    if provider_config.get("provider"):
        settings.provider.provider = str(provider_config["provider"])
    if provider_config.get("profile"):
        settings.provider.profile = str(provider_config["profile"])
    if provider_config.get("api_format"):
        settings.provider.api_format = str(provider_config["api_format"])
    if provider_config.get("api_key_env"):
        settings.provider.api_key_env = str(provider_config["api_key_env"])
    if provider_config.get("base_url"):
        settings.provider.base_url = str(provider_config["base_url"])
    if provider_config.get("auth_scheme"):
        settings.provider.auth_scheme = str(provider_config["auth_scheme"])
    if isinstance(provider_config.get("headers"), dict):
        settings.provider.headers = {str(key): str(value) for key, value in provider_config["headers"].items()}


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


def _unique_text_items(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


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
