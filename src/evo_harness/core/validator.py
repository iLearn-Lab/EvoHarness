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
            steps.append("Validate replay readiness and surface completeness.")
            steps.append(f"Replay the original task: {trace.task_id}")

        if capabilities.regression_suite:
            command_targets = [target for target in trace.validation_targets if _looks_like_executable_validation(target)]
            semantic_targets = [target for target in trace.validation_targets if target not in command_targets]
            if command_targets:
                for target in command_targets:
                    steps.append(f"Run regression validation: {target}")
            else:
                steps.append("Run regression validation: default regression checks")
            if semantic_targets:
                steps.append("Validate deliverable signals: " + ", ".join(semantic_targets))

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


def _looks_like_executable_validation(target: str) -> bool:
    lowered = str(target).strip().lower()
    if not lowered:
        return False
    executable_prefixes = (
        "python ",
        "python -m ",
        "pytest",
        "npm ",
        "pnpm ",
        "yarn ",
        "go ",
        "cargo ",
        "dotnet ",
        "mvn ",
        "gradle ",
        "make ",
        "bash ",
        "cmd ",
        "powershell ",
    )
    return lowered.startswith(executable_prefixes)
