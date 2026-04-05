from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evo_harness.models import AnalysisReport, EvolutionProposal, TaskTrace, WorkspaceSnapshot
from evo_harness.operators.base import BaseOperator


@dataclass(frozen=True, slots=True)
class EcosystemAsset:
    kind: str
    name: str
    target_path: str
    content: str


_ASSET_CATALOG: dict[str, EcosystemAsset] = {
    "skill:long-context-retrieval": EcosystemAsset(
        kind="skill",
        name="long-context-retrieval",
        target_path=".claude/skills/long-context-retrieval.md",
        content="\n".join(
            [
                "---",
                "name: long-context-retrieval",
                "description: Read large files and broad search results progressively instead of flooding the live context window.",
                "---",
                "",
                "# Long Context Retrieval",
                "",
                "- start with grep before broad file reads",
                "- follow next segment and next offset pointers instead of restarting the scan",
                "- stop exploring once you have enough evidence to explain or act",
                "- switch from discovery to explanation when the tool loop is no longer paying off",
                "",
            ]
        ),
    ),
    "agent:context-curator": EcosystemAsset(
        kind="agent",
        name="context-curator",
        target_path=".claude/agents/context-curator.md",
        content="\n".join(
            [
                "---",
                "description: Narrow large files and broad searches into the smallest useful continuation window",
                "tools: workspace_status,list_registry,read_file,grep,glob,read_json",
                "parallel-safe: true",
                "---",
                "",
                "# Context Curator",
                "",
                "- shrink the search space before the parent keeps reading",
                "- prefer exact windows and targeted follow-up reads",
                "- end with the minimum file and segment set worth continuing from",
                "",
            ]
        ),
    ),
    "command:context-pressure": EcosystemAsset(
        kind="command",
        name="context-pressure",
        target_path=".claude/commands/context-pressure.md",
        content="\n".join(
            [
                "---",
                "description: Diagnose long-search and large-file pressure",
                "argument-hint: Pressure source",
                "allowed-tools: workspace_status,list_registry,tool_help,skill,read_file,grep,glob,read_json,run_subagent",
                "---",
                "",
                "# Context Pressure",
                "",
                "Target: $ARGUMENTS",
                "",
                "1. Load `long-context-retrieval` first.",
                "2. Narrow the search space before reading more files.",
                "3. If useful, delegate one bounded pass to `context-curator`.",
                "4. End with the best continuation window instead of an endless scan.",
                "",
            ]
        ),
    ),
    "skill:live-provider-debugging": EcosystemAsset(
        kind="skill",
        name="live-provider-debugging",
        target_path=".claude/skills/live-provider-debugging.md",
        content="\n".join(
            [
                "---",
                "name: live-provider-debugging",
                "description: Diagnose provider compatibility issues such as invalid messages, tool linkage bugs, and empty-turn stalls.",
                "---",
                "",
                "# Live Provider Debugging",
                "",
                "- inspect provider profile, model, and base URL first",
                "- compare the failing transcript shape with the provider's tool-call expectations",
                "- treat malformed messages and repeated empty assistant turns as compatibility signals, not random flakiness",
                "- prefer fixing payload shape and turn compaction before tuning prompts",
                "",
            ]
        ),
    ),
    "agent:provider-debugger": EcosystemAsset(
        kind="agent",
        name="provider-debugger",
        target_path=".claude/agents/provider-debugger.md",
        content="\n".join(
            [
                "---",
                "description: Diagnose live-provider compatibility failures for Kimi, GLM, and other OpenAI-compatible endpoints",
                "tools: workspace_status,list_registry,read_file,grep,glob,read_json",
                "parallel-safe: true",
                "---",
                "",
                "# Provider Debugger",
                "",
                "- inspect provider profile selection, message conversion, and failure shape",
                "- focus on malformed payloads, missing tool linkage, and long-turn compatibility",
                "- finish with one concrete compatibility rule and one patch recommendation",
                "",
            ]
        ),
    ),
    "command:provider-diagnose": EcosystemAsset(
        kind="command",
        name="provider-diagnose",
        target_path=".claude/commands/provider-diagnose.md",
        content="\n".join(
            [
                "---",
                "description: Diagnose Kimi, GLM, and other live-provider compatibility failures",
                "argument-hint: Failure symptom",
                "allowed-tools: workspace_status,list_registry,tool_help,skill,read_file,grep,glob,read_json,run_subagent",
                "---",
                "",
                "# Provider Diagnose",
                "",
                "Symptom: $ARGUMENTS",
                "",
                "1. Load `live-provider-debugging` first.",
                "2. Inspect provider conversion, query compaction, and the failing transcript path.",
                "3. If the failure is subtle, delegate a bounded pass to `provider-debugger`.",
                "4. Summarize the compatibility rule and the smallest safe patch.",
                "",
            ]
        ),
    ),
    "skill:command-authoring": EcosystemAsset(
        kind="skill",
        name="command-authoring",
        target_path=".claude/skills/command-authoring.md",
        content="\n".join(
            [
                "---",
                "name: command-authoring",
                "description: Write markdown commands that constrain workflows cleanly and remain usable in repeated terminal sessions.",
                "---",
                "",
                "# Command Authoring",
                "",
                "- keep commands short enough to run repeatedly",
                "- define inspect, narrow, act, validate, summarize in order",
                "- encode the safe lane with allowed-tools instead of relying on prose alone",
                "- include one explicit recovery step when the first path is blocked",
                "",
            ]
        ),
    ),
    "agent:command-smith": EcosystemAsset(
        kind="agent",
        name="command-smith",
        target_path=".claude/agents/command-smith.md",
        content="\n".join(
            [
                "---",
                "description: Design or revise markdown command workflows for repeated terminal use",
                "tools: workspace_status,list_registry,render_command,read_file,grep,glob,read_json",
                "parallel-safe: true",
                "---",
                "",
                "# Command Smith",
                "",
                "- study nearby commands, allowed-tools policies, and likely recovery paths",
                "- keep command workflows tight, repeatable, and easy to validate",
                "- propose command changes in terms of workflow shape, not only wording",
                "",
            ]
        ),
    ),
    "command:validation-gate": EcosystemAsset(
        kind="command",
        name="validation-gate",
        target_path=".claude/commands/validation-gate.md",
        content="\n".join(
            [
                "---",
                "description: Audit replay, regression, and rollback gates before promoting an evolution candidate",
                "argument-hint: Candidate or workflow",
                "allowed-tools: workspace_status,list_registry,tool_help,skill,read_file,grep,glob,read_json,task_control,run_subagent",
                "---",
                "",
                "# Validation Gate",
                "",
                "Candidate: $ARGUMENTS",
                "",
                "1. Load `validation-gating` first.",
                "2. Inspect replay, regression, rollback, and promotion policy surfaces.",
                "3. If needed, delegate a bounded review to `validation-guardian`.",
                "4. Conclude with what is safe now, what is blocked, and what evidence is missing.",
                "",
            ]
        ),
    ),
    "skill:ecosystem-gap-review": EcosystemAsset(
        kind="skill",
        name="ecosystem-gap-review",
        target_path=".claude/skills/ecosystem-gap-review.md",
        content="\n".join(
            [
                "---",
                "name: ecosystem-gap-review",
                "description: Identify which missing commands, skills, agents, or MCP assets most improve engineering throughput.",
                "---",
                "",
                "# Ecosystem Gap Review",
                "",
                "- rank missing assets by engineering leverage, not novelty",
                "- prefer assets that shorten future turns, reduce retries, or improve safety",
                "- call out whether the gap should be solved by a skill, command, agent, plugin, or MCP addition",
                "",
            ]
        ),
    ),
    "agent:ecosystem-gardener": EcosystemAsset(
        kind="agent",
        name="ecosystem-gardener",
        target_path=".claude/agents/ecosystem-gardener.md",
        content="\n".join(
            [
                "---",
                "description: Review the harness ecosystem and recommend the next highest-leverage asset to add",
                "tools: workspace_status,list_registry,read_file,grep,glob,mcp_registry_detail",
                "parallel-safe: true",
                "---",
                "",
                "# Ecosystem Gardener",
                "",
                "- inspect commands, skills, agents, plugins, and MCP together",
                "- look for sparse or duplicated areas",
                "- recommend additions that increase actual day-to-day utility",
                "",
            ]
        ),
    ),
    "command:grow-ecosystem": EcosystemAsset(
        kind="command",
        name="grow-ecosystem",
        target_path=".claude/commands/grow-ecosystem.md",
        content="\n".join(
            [
                "---",
                "description: Review what commands, skills, agents, plugins, and MCP assets the harness should add next",
                "argument-hint: Gap to address",
                "allowed-tools: workspace_status,list_registry,tool_help,skill,read_file,grep,glob,mcp_registry_detail,run_subagent",
                "---",
                "",
                "# Grow Ecosystem",
                "",
                "Gap: $ARGUMENTS",
                "",
                "1. Load `ecosystem-gap-review` first.",
                "2. Inspect the current command, skill, agent, plugin, and MCP surface.",
                "3. If useful, delegate one bounded pass to `ecosystem-gardener`.",
                "4. Recommend the next highest-leverage additions, not just the largest list.",
                "",
            ]
        ),
    ),
}

_BUNDLES: dict[str, dict[str, Any]] = {
    "deep-inspection-stability": {
        "summary": "Add a long-context reading bundle so deep code explanations converge instead of spiraling into file loops.",
        "why": "This bundle reduces context pressure and gives the harness a reusable way to narrow large explanations.",
        "assets": [
            "skill:long-context-retrieval",
            "agent:context-curator",
            "command:context-pressure",
        ],
        "follow_up_bundles": ["growth-planning"],
    },
    "provider-resilience": {
        "summary": "Add a provider-debugging bundle so live OpenAI-compatible failures can be diagnosed quickly and safely.",
        "why": "This bundle turns provider-specific debugging from ad-hoc investigation into a repeatable workflow.",
        "assets": [
            "skill:live-provider-debugging",
            "agent:provider-debugger",
            "command:provider-diagnose",
        ],
        "follow_up_bundles": ["deep-inspection-stability"],
    },
    "workflow-guardrails": {
        "summary": "Add a command-design and validation bundle so command workflows recover cleanly instead of trapping the user.",
        "why": "This bundle improves command authoring, recovery steps, and promotion safety for future workflow changes.",
        "assets": [
            "skill:command-authoring",
            "agent:command-smith",
            "command:validation-gate",
        ],
        "follow_up_bundles": ["growth-planning"],
    },
    "growth-planning": {
        "summary": "Add an ecosystem-planning bundle so the harness can reason about which commands, skills, and agents are still missing.",
        "why": "This bundle gives the harness an explicit path for growth planning instead of vague ecosystem commentary.",
        "assets": [
            "skill:ecosystem-gap-review",
            "agent:ecosystem-gardener",
            "command:grow-ecosystem",
        ],
        "follow_up_bundles": [],
    },
}


class GrowEcosystemOperator(BaseOperator):
    """Plan a concrete command/skill/agent bundle that expands the harness surface."""

    def build_change_request(
        self,
        trace: TaskTrace,
        workspace: WorkspaceSnapshot,
        report: AnalysisReport,
        proposal: EvolutionProposal,
    ) -> dict[str, Any]:
        bundle_name = str(proposal.metadata.get("bundle_name", "growth-planning"))
        bundle = _BUNDLES[bundle_name]
        missing_assets = _missing_assets(workspace, bundle["assets"])
        scaffold_assets = [_asset_payload(asset_key) for asset_key in missing_assets]
        target_files = [asset["target_path"] for asset in scaffold_assets]
        return {
            "operator": "grow_ecosystem",
            "bundle_name": bundle_name,
            "summary": bundle["summary"],
            "why": bundle["why"],
            "evidence": {
                "task_id": trace.task_id,
                "summary": trace.summary,
                "error_tags": trace.error_tags,
                "findings": [finding.to_dict() for finding in report.findings],
                "workspace_counts": {
                    "skills": len(workspace.skill_files),
                    "commands": len(workspace.command_files),
                    "agents": len(workspace.agent_files),
                },
            },
            "scaffold_assets": scaffold_assets,
            "target_files": target_files,
            "follow_up_bundles": list(bundle.get("follow_up_bundles", [])),
            "promotion_policy": proposal.validator_steps,
        }


def ecosystem_bundle_name_for_trace(trace: TaskTrace, report: AnalysisReport) -> str:
    kinds = {finding.kind for finding in report.findings}
    tags = set(trace.error_tags)
    if "provider_gap" in kinds or "provider_stall" in tags:
        return "provider-resilience"
    if "command_gap" in kinds or "command_policy_pressure" in tags:
        return "workflow-guardrails"
    if "context_pressure" in kinds or "exploration_loop" in tags:
        return "deep-inspection-stability"
    return "growth-planning"


def ecosystem_bundle_missing_assets(bundle_name: str, workspace: WorkspaceSnapshot) -> list[str]:
    return _missing_assets(workspace, _BUNDLES[bundle_name]["assets"])


def _missing_assets(workspace: WorkspaceSnapshot, asset_keys: list[str]) -> list[str]:
    existing = {
        "skill": {_normalized_stem(path) for path in workspace.skill_files},
        "command": {_normalized_stem(path) for path in workspace.command_files},
        "agent": {_normalized_stem(path) for path in workspace.agent_files},
    }
    missing: list[str] = []
    for key in asset_keys:
        kind, name = key.split(":", 1)
        if _normalized_name(name) not in existing.get(kind, set()):
            missing.append(key)
    return missing


def _asset_payload(asset_key: str) -> dict[str, str]:
    asset = _ASSET_CATALOG[asset_key]
    return {
        "kind": asset.kind,
        "name": asset.name,
        "target_path": asset.target_path,
        "content": asset.content,
    }


def _normalized_stem(path_str: str) -> str:
    return _normalized_name(Path(path_str).stem)


def _normalized_name(name: str) -> str:
    return name.replace("_", "-").replace(" ", "-").lower()
