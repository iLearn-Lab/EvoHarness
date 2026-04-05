from __future__ import annotations

from evo_harness.models import AnalysisReport, EvolutionProposal, TaskTrace, WorkspaceSnapshot
from evo_harness.operators.base import BaseOperator


class StopOperator(BaseOperator):
    """Return a no-op control decision when evolution is not yet justified."""

    def build_change_request(
        self,
        trace: TaskTrace,
        workspace: WorkspaceSnapshot,
        report: AnalysisReport,
        proposal: EvolutionProposal,
    ) -> dict[str, object]:
        del workspace
        return {
            "operator": "stop",
            "summary": "Do not mutate the harness yet.",
            "reason": proposal.reason,
            "next_action": "Collect more traces, compare across sessions, and retry when validation is available.",
            "evidence": {
                "task_id": trace.task_id,
                "risk_score": report.risk_score,
            },
        }

