from __future__ import annotations

from evo_harness.models import AnalysisReport, EvolutionProposal, TaskTrace, WorkspaceSnapshot
from evo_harness.operators.base import BaseOperator


class ReviseCommandOperator(BaseOperator):
    """Build a command revision request for markdown workflow commands."""

    def build_change_request(
        self,
        trace: TaskTrace,
        workspace: WorkspaceSnapshot,
        report: AnalysisReport,
        proposal: EvolutionProposal,
    ) -> dict[str, object]:
        target_command = proposal.change_targets[0] if proposal.change_targets else "workspace-command"
        preferred_path = str(trace.artifacts.get("active_command_path") or ".claude/commands/generated-fix.md")
        return {
            "operator": "revise_command",
            "target_command": target_command,
            "preferred_path": preferred_path,
            "summary": "Patch a failing command workflow and validate it before promotion.",
            "evidence": {
                "task_id": trace.task_id,
                "summary": trace.summary,
                "error_tags": trace.error_tags,
                "findings": [finding.to_dict() for finding in report.findings],
                "active_command_name": trace.artifacts.get("active_command_name"),
            },
            "proposed_updates": [
                "Clarify the intended workflow and allowed tools for this command.",
                "Add one explicit recovery step when the first approach is blocked.",
                "Keep the command concise enough for repeated runtime use.",
            ],
            "promotion_policy": proposal.validator_steps,
        }
