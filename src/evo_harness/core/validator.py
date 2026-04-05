from __future__ import annotations

from evo_harness.models import EvolutionProposal, HarnessCapabilities, OperatorName, TaskTrace


class ValidationPlanner:
    """Build validation gates before any evolution is promoted."""

    def build_steps(
        self,
        proposal: EvolutionProposal,
        capabilities: HarnessCapabilities,
        trace: TaskTrace,
    ) -> list[str]:
        if proposal.operator == OperatorName.STOP:
            return ["Skip mutation and keep collecting traces."]

        steps: list[str] = []

        if capabilities.replay_validation:
            steps.append(f"Replay the original task: {trace.task_id}")

        if capabilities.regression_suite:
            target = ", ".join(trace.validation_targets) or "default regression checks"
            steps.append(f"Run regression validation: {target}")

        if proposal.operator == OperatorName.REVISE_SKILL and capabilities.skill_validate:
            steps.append("Validate the revised skill before promotion.")

        if proposal.operator == OperatorName.REVISE_COMMAND and capabilities.slash_commands:
            steps.append("Validate the revised command workflow before promotion.")

        if proposal.operator == OperatorName.GROW_ECOSYSTEM:
            steps.append("Validate that the new ecosystem assets are discoverable before promotion.")
            steps.append("Review whether the bundle actually shortens future engineering work.")

        if capabilities.skill_rollback:
            steps.append("Keep a rollback snapshot until the next healthy run.")

        return steps

    def is_safe(self, proposal: EvolutionProposal, capabilities: HarnessCapabilities) -> bool:
        if not proposal.required_capabilities:
            return True
        return capabilities.supports(*proposal.required_capabilities)
