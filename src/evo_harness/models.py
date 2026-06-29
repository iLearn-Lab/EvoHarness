from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal


class Outcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"


class OperatorName(str, Enum):
    GROW_ECOSYSTEM = "grow_ecosystem"
    REVISE_SKILL = "revise_skill"
    REVISE_COMMAND = "revise_command"
    DISTILL_MEMORY = "distill_memory"
    STOP = "stop"


NegativeControlOutcome = Literal["no_match", "decline", "route_elsewhere", "no_capability_claim"]
NegativeControlSource = Literal["trace", "proposal", "policy", "manual"]

NEGATIVE_CONTROL_OUTCOMES: set[str] = {"no_match", "decline", "route_elsewhere", "no_capability_claim"}
NEGATIVE_CONTROL_SOURCES: set[str] = {"trace", "proposal", "policy", "manual"}


@dataclass(slots=True)
class NegativeControlProbe:
    name: str
    prompt: str
    expected_outcome: NegativeControlOutcome = "decline"
    source: NegativeControlSource = "trace"

    @classmethod
    def from_raw(
        cls,
        raw: "NegativeControlProbe | dict[str, Any] | str",
        *,
        default_source: NegativeControlSource = "trace",
        fallback_name: str = "negative_control",
    ) -> "NegativeControlProbe":
        if isinstance(raw, cls):
            return raw
        if isinstance(raw, dict):
            prompt = str(raw.get("prompt") or raw.get("target") or raw.get("query") or raw.get("text") or "").strip()
            name = str(raw.get("name") or raw.get("id") or fallback_name).strip() or fallback_name
            expected = _normalize_negative_control_outcome(raw.get("expected_outcome") or raw.get("expected"))
            source = _normalize_negative_control_source(raw.get("source"), default_source=default_source)
            return cls(name=name, prompt=prompt, expected_outcome=expected, source=source)
        prompt = str(raw).strip()
        return cls(name=fallback_name, prompt=prompt, expected_outcome="decline", source=default_source)

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _normalize_negative_control_outcome(value: Any) -> NegativeControlOutcome:
    text = str(value or "decline").strip().lower().replace("-", "_")
    if text not in NEGATIVE_CONTROL_OUTCOMES:
        text = "decline"
    return text  # type: ignore[return-value]


def _normalize_negative_control_source(
    value: Any,
    *,
    default_source: NegativeControlSource = "trace",
) -> NegativeControlSource:
    text = str(value or default_source).strip().lower().replace("-", "_")
    if text not in NEGATIVE_CONTROL_SOURCES:
        text = default_source
    return text  # type: ignore[return-value]


@dataclass(slots=True)
class HarnessCapabilities:
    adapter_name: str
    skill_upgrade: bool = False
    skill_validate: bool = False
    skill_rollback: bool = False
    memory_write: bool = False
    memory_archive: bool = False
    session_fork: bool = False
    agent_clone: bool = False
    replay_validation: bool = False
    regression_suite: bool = False
    artifact_access: bool = False
    execution_history: bool = False
    hooks: bool = False
    subagents: bool = False
    slash_commands: bool = False
    permission_rules: bool = False
    workspace_instructions: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HarnessCapabilities":
        features = data.get("features", data)
        return cls(
            adapter_name=data.get("adapter_name", data.get("name", "unknown")),
            skill_upgrade=bool(features.get("skill_upgrade", False)),
            skill_validate=bool(features.get("skill_validate", False)),
            skill_rollback=bool(features.get("skill_rollback", False)),
            memory_write=bool(features.get("memory_write", False)),
            memory_archive=bool(features.get("memory_archive", False)),
            session_fork=bool(features.get("session_fork", False)),
            agent_clone=bool(features.get("agent_clone", False)),
            replay_validation=bool(features.get("replay_validation", False)),
            regression_suite=bool(features.get("regression_suite", False)),
            artifact_access=bool(features.get("artifact_access", False)),
            execution_history=bool(features.get("execution_history", False)),
            hooks=bool(features.get("hooks", False)),
            subagents=bool(features.get("subagents", False)),
            slash_commands=bool(features.get("slash_commands", False)),
            permission_rules=bool(features.get("permission_rules", False)),
            workspace_instructions=bool(features.get("workspace_instructions", False)),
        )

    def supports(self, *capabilities: str) -> bool:
        return all(getattr(self, capability, False) for capability in capabilities)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TaskTrace:
    task_id: str
    harness: str
    outcome: Outcome
    summary: str
    repeated_failures: int = 0
    reusable_success_pattern: bool = False
    error_tags: list[str] = field(default_factory=list)
    tool_calls: int = 0
    token_cost: int = 0
    token_budget: int = 0
    validation_targets: list[str] = field(default_factory=list)
    negative_control_targets: list[str] = field(default_factory=list)
    negative_control_probes: list[NegativeControlProbe] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskTrace":
        return cls(
            task_id=data["task_id"],
            harness=data["harness"],
            outcome=Outcome(data["outcome"]),
            summary=data.get("summary", ""),
            repeated_failures=int(data.get("repeated_failures", 0)),
            reusable_success_pattern=bool(data.get("reusable_success_pattern", False)),
            error_tags=list(data.get("error_tags", [])),
            tool_calls=int(data.get("tool_calls", 0)),
            token_cost=int(data.get("token_cost", 0)),
            token_budget=int(data.get("token_budget", 0)),
            validation_targets=list(data.get("validation_targets", [])),
            negative_control_targets=list(data.get("negative_control_targets", data.get("overclaim_targets", []))),
            negative_control_probes=[
                NegativeControlProbe.from_raw(item, default_source="trace", fallback_name=f"trace_negative_control_{index + 1}")
                for index, item in enumerate(data.get("negative_control_probes", data.get("overclaim_probes", [])))
            ],
            artifacts=dict(data.get("artifacts", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["outcome"] = self.outcome.value
        return payload


@dataclass(slots=True)
class WorkspaceSnapshot:
    root: str
    claude_files: list[str] = field(default_factory=list)
    memory_files: list[str] = field(default_factory=list)
    skill_files: list[str] = field(default_factory=list)
    command_files: list[str] = field(default_factory=list)
    agent_files: list[str] = field(default_factory=list)
    hook_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvolutionFinding:
    kind: str
    severity: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AnalysisReport:
    task_id: str
    findings: list[EvolutionFinding]
    risk_score: float
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "findings": [finding.to_dict() for finding in self.findings],
            "risk_score": self.risk_score,
            "summary": self.summary,
        }


@dataclass(slots=True)
class EvolutionProposal:
    operator: OperatorName
    reason: str
    confidence: float
    required_capabilities: list[str] = field(default_factory=list)
    change_targets: list[str] = field(default_factory=list)
    validator_steps: list[str] = field(default_factory=list)
    negative_control_probes: list[NegativeControlProbe] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["operator"] = self.operator.value
        return payload


@dataclass(slots=True)
class AutonomousEvolutionAssessment:
    needs_evolution: bool
    operator: str
    outcome: str
    confidence: float
    summary: str
    error_tags: list[str] = field(default_factory=list)
    capability_gap: dict[str, Any] | None = None
    skill_name: str | None = None
    bundle_name: str | None = None
    replay_prompt: str | None = None
    evidence: list[str] = field(default_factory=list)
    raw_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TaskRequirementGraph:
    capability_name: str
    input_objects: list[str] = field(default_factory=list)
    input_formats: list[str] = field(default_factory=list)
    environment_targets: list[str] = field(default_factory=list)
    deliverables: list[str] = field(default_factory=list)
    workflow_actions: list[str] = field(default_factory=list)
    requested_surfaces: list[str] = field(default_factory=list)
    requested_growth_unit: list[str] = field(default_factory=list)
    domain_tags: list[str] = field(default_factory=list)
    state_targets: list[str] = field(default_factory=list)
    operation_specs: list[dict[str, Any]] = field(default_factory=list)
    reuse_across_sessions: bool = False
    external_dependencies: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    research_plan: dict[str, Any] = field(default_factory=dict)
    implementation_contract: dict[str, Any] = field(default_factory=dict)
    replay_contract: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CapabilitySurfaceGraph:
    commands: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    dependency_markers: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CapabilityGrowthPlan:
    capability_name: str
    capability_slug: str
    gap_types: list[str] = field(default_factory=list)
    minimal_growth_unit: list[str] = field(default_factory=list)
    preferred_surfaces: list[str] = field(default_factory=list)
    required_assets: list[str] = field(default_factory=list)
    dependency_hints: list[str] = field(default_factory=list)
    validation_hints: list[str] = field(default_factory=list)
    workflow_outline: list[str] = field(default_factory=list)
    synthesis_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvolutionPlan:
    trace: TaskTrace
    capabilities: HarnessCapabilities
    workspace: WorkspaceSnapshot
    report: AnalysisReport
    proposal: EvolutionProposal
    safe_to_apply: bool
    change_request: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace": self.trace.to_dict(),
            "capabilities": self.capabilities.to_dict(),
            "workspace": self.workspace.to_dict(),
            "report": self.report.to_dict(),
            "proposal": self.proposal.to_dict(),
            "safe_to_apply": self.safe_to_apply,
            "change_request": self.change_request,
        }
