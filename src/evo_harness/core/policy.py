from __future__ import annotations

from pathlib import Path

from evo_harness.models import (
    AnalysisReport,
    EvolutionProposal,
    HarnessCapabilities,
    OperatorName,
    Outcome,
    TaskTrace,
    WorkspaceSnapshot,
)
from evo_harness.operators.grow_ecosystem import ecosystem_bundle_missing_assets, ecosystem_bundle_name_for_trace


class EvolutionPolicy:
    """Choose the safest high-value evolution move for the current trace."""

    def decide(
        self,
        trace: TaskTrace,
        capabilities: HarnessCapabilities,
        workspace: WorkspaceSnapshot,
        report: AnalysisReport,
    ) -> EvolutionProposal:
        kinds = {finding.kind for finding in report.findings}

        if (
            trace.outcome in {Outcome.FAILURE, Outcome.PARTIAL}
            and "command_gap" in kinds
            and trace.artifacts.get("active_command_name")
            and capabilities.supports("slash_commands", "skill_validate", "replay_validation")
        ):
            target = str(trace.artifacts.get("active_command_name", "workspace-command"))
            return EvolutionProposal(
                operator=OperatorName.REVISE_COMMAND,
                reason=(
                    "The failing run happened inside an active command workflow, and the harness can "
                    "safely update markdown commands with validation and replay gates."
                ),
                confidence=0.86,
                required_capabilities=["slash_commands", "skill_validate", "replay_validation"],
                change_targets=[target],
                metadata={
                    "active_command_path": trace.artifacts.get("active_command_path"),
                    "workspace_has_command_workflow": bool(trace.artifacts.get("active_command_name")),
                },
            )

        requested_bundle = str(trace.artifacts.get("bundle_name", "") or "").strip()
        bundle_name = requested_bundle or ecosystem_bundle_name_for_trace(trace, report)
        missing_bundle_assets = ecosystem_bundle_missing_assets(bundle_name, workspace)
        if (
            trace.outcome in {Outcome.FAILURE, Outcome.PARTIAL}
            and {"ecosystem_gap", "provider_gap", "context_pressure"} & kinds
            and missing_bundle_assets
            and capabilities.supports("artifact_access", "workspace_instructions")
        ):
            return EvolutionProposal(
                operator=OperatorName.GROW_ECOSYSTEM,
                reason=(
                    "The trace points to a thin harness surface, so the safest high-leverage move is to "
                    "add a bounded command/skill/agent bundle instead of patching only one artifact in isolation."
                ),
                confidence=0.8,
                required_capabilities=["artifact_access", "workspace_instructions"],
                change_targets=missing_bundle_assets,
                metadata={
                    "bundle_name": bundle_name,
                    "missing_assets": missing_bundle_assets,
                    "workspace_skill_count": len(workspace.skill_files),
                    "workspace_command_count": len(workspace.command_files),
                    "workspace_agent_count": len(workspace.agent_files),
                },
            )

        if (
            trace.outcome in {Outcome.FAILURE, Outcome.PARTIAL}
            and {"skill_gap", "repeated_failure", "ecosystem_gap", "provider_gap", "context_pressure"} & kinds
            and capabilities.supports("skill_upgrade", "skill_validate", "replay_validation")
        ):
            target = str(trace.artifacts.get("skill_name", _default_skill_target(workspace, trace)))
            return EvolutionProposal(
                operator=OperatorName.REVISE_SKILL,
                reason=(
                    "The trace points to a reusable workflow or ecosystem gap, and the harness "
                    "has enough capability to revise and validate a skill safely."
                ),
                confidence=0.83,
                required_capabilities=["skill_upgrade", "skill_validate", "replay_validation"],
                change_targets=[target],
                metadata={
                    "workspace_has_claude_md": bool(workspace.claude_files),
                    "workspace_skill_count": len(workspace.skill_files),
                    "workspace_command_count": len(workspace.command_files),
                    "workspace_agent_count": len(workspace.agent_files),
                },
            )

        if (
            ("reusable_success" in kinds or "memory_drift" in kinds)
            and capabilities.supports("memory_write")
        ):
            return EvolutionProposal(
                operator=OperatorName.DISTILL_MEMORY,
                reason=(
                    "The harness surfaced a reusable lesson or stale memory issue, so the "
                    "safest leverage point is to update persistent memory first."
                ),
                confidence=0.76,
                required_capabilities=["memory_write"],
                change_targets=["MEMORY.md"],
                metadata={
                    "workspace_memory_count": len(workspace.memory_files),
                },
            )

        return EvolutionProposal(
            operator=OperatorName.STOP,
            reason=(
                "The trace does not justify a safe evolution step with the current harness "
                "capabilities, so the system should stop and keep observing."
            ),
            confidence=0.92,
            required_capabilities=[],
            change_targets=[],
            metadata={"risk_score": report.risk_score},
        )


def _default_skill_target(workspace: WorkspaceSnapshot, trace: TaskTrace) -> str:
    requested = str(trace.artifacts.get("skill_name", "") or "").strip()
    if requested:
        return requested
    available = {Path(path).stem for path in workspace.skill_files}
    for candidate in ("long-context-retrieval", "live-provider-debugging", "self-evolution-triage", "harness-ecosystem"):
        if candidate in available:
            return candidate
    return "workspace-skill"
