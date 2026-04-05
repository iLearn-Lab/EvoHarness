from __future__ import annotations

from evo_harness.models import AnalysisReport, EvolutionProposal, TaskTrace, WorkspaceSnapshot
from evo_harness.operators.base import BaseOperator


class ReviseSkillOperator(BaseOperator):
    """Build a skill revision request for harness-native skills."""

    def build_change_request(
        self,
        trace: TaskTrace,
        workspace: WorkspaceSnapshot,
        report: AnalysisReport,
        proposal: EvolutionProposal,
    ) -> dict[str, object]:
        target_skill = proposal.change_targets[0] if proposal.change_targets else "workspace-skill"
        preferred_path = _preferred_skill_path(workspace, str(target_skill))
        return {
            "operator": "revise_skill",
            "target_skill": target_skill,
            "preferred_path": preferred_path,
            "summary": "Patch a failing harness skill or workflow and validate it before promotion.",
            "evidence": {
                "task_id": trace.task_id,
                "summary": trace.summary,
                "error_tags": trace.error_tags,
                "findings": [finding.to_dict() for finding in report.findings],
            },
            "proposed_updates": [
                "Tighten the skill instructions around the failing tool or workflow.",
                "Add one explicit success pattern and one failure-avoidance rule.",
                "Keep the skill short enough to remain workspace-friendly.",
            ],
            "promotion_policy": proposal.validator_steps,
        }


def _preferred_skill_path(workspace: WorkspaceSnapshot, target_skill: str) -> str:
    normalized_target = target_skill.replace("_", "-").replace(" ", "-").lower()
    for path in workspace.skill_files:
        candidate = path.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0].replace("_", "-").lower()
        if candidate == normalized_target:
            return path
    return workspace.skill_files[0] if workspace.skill_files else ".claude/skills/generated-fix.md"
