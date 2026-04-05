from __future__ import annotations

from evo_harness.models import AnalysisReport, EvolutionProposal, TaskTrace, WorkspaceSnapshot
from evo_harness.operators.base import BaseOperator


class DistillMemoryOperator(BaseOperator):
    """Build a memory distillation request for persistent harness learning."""

    def build_change_request(
        self,
        trace: TaskTrace,
        workspace: WorkspaceSnapshot,
        report: AnalysisReport,
        proposal: EvolutionProposal,
    ) -> dict[str, object]:
        memory_target = workspace.memory_files[0] if workspace.memory_files else "MEMORY.md"
        return {
            "operator": "distill_memory",
            "target_memory": memory_target,
            "summary": "Capture a reusable lesson in persistent memory without touching runtime code first.",
            "lesson_template": {
                "title": f"Lesson from {trace.task_id}",
                "when_to_use": "When a similar harness task or tool path appears again.",
                "pattern": trace.summary,
                "avoid": "Do not blindly reuse stale or contradicted instructions.",
            },
            "evidence": {
                "findings": [finding.to_dict() for finding in report.findings],
                "artifacts": trace.artifacts,
            },
            "promotion_policy": proposal.validator_steps,
        }

