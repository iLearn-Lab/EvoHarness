from __future__ import annotations

from pathlib import Path

from evo_harness.core import EvolutionPolicy, TraceAnalyzer, ValidationPlanner, discover_workspace
from evo_harness.models import EvolutionPlan, HarnessCapabilities, OperatorName, TaskTrace
from evo_harness.operators import DistillMemoryOperator, GrowEcosystemOperator, ReviseCommandOperator, ReviseSkillOperator, StopOperator


class EvolutionEngine:
    """A thin control plane that sits on top of an existing agent harness."""

    def __init__(self) -> None:
        self._analyzer = TraceAnalyzer()
        self._policy = EvolutionPolicy()
        self._validator = ValidationPlanner()
        self._operators = {
            OperatorName.GROW_ECOSYSTEM: GrowEcosystemOperator(),
            OperatorName.REVISE_SKILL: ReviseSkillOperator(),
            OperatorName.REVISE_COMMAND: ReviseCommandOperator(),
            OperatorName.DISTILL_MEMORY: DistillMemoryOperator(),
            OperatorName.STOP: StopOperator(),
        }

    def plan(
        self,
        *,
        trace: TaskTrace,
        capabilities: HarnessCapabilities,
        workspace_root: str | Path,
    ) -> EvolutionPlan:
        workspace = discover_workspace(workspace_root)
        report = self._analyzer.analyze(trace)
        proposal = self._policy.decide(trace, capabilities, workspace, report)
        proposal.validator_steps = self._validator.build_steps(proposal, capabilities, trace)
        safe_to_apply = self._validator.is_safe(proposal, capabilities)
        change_request = self._operators[proposal.operator].build_change_request(
            trace,
            workspace,
            report,
            proposal,
        )
        return EvolutionPlan(
            trace=trace,
            capabilities=capabilities,
            workspace=workspace,
            report=report,
            proposal=proposal,
            safe_to_apply=safe_to_apply,
            change_request=change_request,
        )
