from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evo_harness.models import AnalysisReport, EvolutionProposal, TaskTrace, WorkspaceSnapshot
from evo_harness.operators.base import BaseOperator
from evo_harness.operators.capability_growth import build_generic_capability_growth_change_request


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
    "skill:document-task-bootstrap": EcosystemAsset(
        kind="skill",
        name="document-task-bootstrap",
        target_path=".claude/skills/document-task-bootstrap.md",
        content="\n".join(
            [
                "---",
                "name: document-task-bootstrap",
                "description: Handle Word/docx tasks through persistent plugin and MCP assets instead of rediscovering the setup every session.",
                "---",
                "",
                "# Document Task Bootstrap",
                "",
                "- start with `list_registry` or `mcp_registry_detail` and look for `document-automation:doc-tools`",
                "- use `mcp_call_tool` with `inspect_document_support` before assuming .doc or .docx support",
                "- prefer `read_document_text` and `write_report_docx` over ad-hoc shell tricks for report work",
                "- if the source is legacy `.doc`, say whether Word automation or conversion is still required",
                "- keep the final report structured with title, objective, method, results, analysis, and conclusion",
                "",
            ]
        ),
    ),
    "agent:document-operator": EcosystemAsset(
        kind="agent",
        name="document-operator",
        target_path=".claude/agents/document-operator.md",
        content="\n".join(
            [
                "---",
                "description: Operate document-focused workflows through the document automation MCP surface",
                "tools: list_registry,mcp_registry_detail,mcp_call_tool,read_file,write_file",
                "parallel-safe: false",
                "---",
                "",
                "# Document Operator",
                "",
                "- confirm document support before reading or writing files",
                "- treat `.docx` as first-class and `.doc` as best-effort unless Word automation is available",
                "- keep generated reports clean, structured, and easy to validate",
                "",
            ]
        ),
    ),
    "command:word-lab-report": EcosystemAsset(
        kind="command",
        name="word-lab-report",
        target_path=".claude/commands/word-lab-report.md",
        content="\n".join(
            [
                "---",
                "description: Read a Word-style assignment, draft a lab report, and write a `.docx` output through MCP-backed document tools",
                "argument-hint: Assignment path or topic",
                "allowed-tools: list_registry,tool_help,skill,mcp_registry_detail,mcp_call_tool,read_file,write_file",
                "---",
                "",
                "# Word Lab Report",
                "",
                "Task: $ARGUMENTS",
                "",
                "1. Load `document-task-bootstrap` first.",
                "2. Confirm `document-automation:doc-tools` support with `inspect_document_support`.",
                "3. If the assignment is a `.docx`, use `read_document_text` to extract the brief.",
                "4. Draft a report with objective, materials, steps, results, analysis, and conclusion.",
                "5. Use `write_report_docx` to save the final report and summarize any remaining format limits.",
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
    "document-automation": {
        "summary": "Add a persistent Word/docx workflow bundle so document tasks stop requiring one-off rediscovery and setup.",
        "why": "This bundle turns document requests into a reusable plugin, MCP surface, and command workflow that survive across sessions.",
        "assets": [
            "skill:document-task-bootstrap",
            "agent:document-operator",
            "command:word-lab-report",
        ],
        "follow_up_bundles": ["workflow-guardrails"],
    },
    "capability-growth": {
        "summary": "Add a new reusable capability bundle derived from the autonomous evolution assessment.",
        "why": "This bundle is generated from a capability gap discovered in a real session rather than from a fixed hard-coded category list.",
        "assets": [],
        "follow_up_bundles": ["workflow-guardrails"],
    },
}

_EXTRA_BUNDLE_ASSETS: dict[str, list[dict[str, str]]] = {
    "document-automation": [
        {
            "kind": "plugin",
            "name": "document-automation-plugin",
            "target_path": "plugins/document-automation/.claude-plugin/plugin.json",
            "content": json.dumps(
                {
                    "name": "document-automation",
                    "version": "0.1.0",
                    "description": "Persistent Word/docx helpers with MCP-backed document extraction and report generation.",
                    "enabled_by_default": True,
                    "skills_dir": "skills",
                    "commands_dir": "commands",
                    "agents_dir": "agents",
                    "mcp_file": ".mcp.json",
                    "tags": ["documents", "word", "docx", "mcp"],
                },
                indent=2,
                ensure_ascii=False,
            ),
        },
        {
            "kind": "plugin",
            "name": "document-automation-mcp",
            "target_path": "plugins/document-automation/.mcp.json",
            "content": json.dumps(
                {
                    "mcpServers": {
                        "doc-tools": {
                            "transport": "stdio",
                            "command": "python",
                            "args": ["-m", "evo_harness.document_automation_mcp_server"],
                            "description": "Word/docx support helpers for extracting text and writing structured .docx reports.",
                            "tools": [
                                {
                                    "name": "inspect_document_support",
                                    "description": "Describe current .doc and .docx support in this workspace.",
                                },
                                {
                                    "name": "read_document_text",
                                    "description": "Read text from a .docx document or attempt best-effort .doc extraction.",
                                },
                                {
                                    "name": "write_report_docx",
                                    "description": "Write a structured lab-style report to a .docx file.",
                                },
                            ],
                            "prompts": [
                                {
                                    "name": "draft_lab_report",
                                    "description": "Turn an assignment brief into a structured lab report outline.",
                                }
                            ],
                        }
                    }
                },
                indent=2,
                ensure_ascii=False,
            ),
        },
    ]
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
        if bundle_name not in _BUNDLES:
            bundle_name = "capability-growth" if trace.artifacts.get("capability_gap") else "growth-planning"
        bundle = _BUNDLES[bundle_name]
        if bundle_name == "capability-growth":
            generic_request = build_generic_capability_growth_change_request(trace, workspace)
            scaffold_assets = list(generic_request.get("scaffold_assets", []))
        else:
            generic_request = {}
            missing_assets = _missing_assets(workspace, bundle["assets"])
            scaffold_assets = [_asset_payload(asset_key) for asset_key in missing_assets]
            scaffold_assets.extend(_bundle_extra_assets(bundle_name, workspace))
        target_files = [asset["target_path"] for asset in scaffold_assets]
        change_request = {
            "operator": "grow_ecosystem",
            "bundle_name": bundle_name,
            "summary": bundle["summary"],
            "why": bundle["why"],
            "evidence": {
                "task_id": trace.task_id,
                "summary": trace.summary,
                "error_tags": trace.error_tags,
                "findings": [finding.to_dict() for finding in report.findings],
                "capability_gap": trace.artifacts.get("capability_gap"),
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
        if generic_request:
            change_request.update(
                {
                    "requirement_graph": generic_request.get("requirement_graph", {}),
                    "surface_graph": generic_request.get("surface_graph", {}),
                    "capability_plan": generic_request.get("capability_plan", {}),
                    "research_plan": generic_request.get("research_plan", {}),
                    "implementation_contract": generic_request.get("implementation_contract", {}),
                    "replay_contract": generic_request.get("replay_contract", {}),
                }
            )
        return change_request


def ecosystem_bundle_name_for_trace(trace: TaskTrace, report: AnalysisReport) -> str:
    explicit_bundle = str(trace.artifacts.get("bundle_name", "") or "").strip()
    if explicit_bundle in _BUNDLES:
        return explicit_bundle
    capability_gap = dict(trace.artifacts.get("capability_gap", {}) or {})
    gap_bundle = str(capability_gap.get("bundle_name", "") or "").strip()
    if gap_bundle in _BUNDLES:
        return gap_bundle
    if capability_gap:
        return "capability-growth"
    kinds = {finding.kind for finding in report.findings}
    tags = set(trace.error_tags)
    if "provider_gap" in kinds or "provider_stall" in tags:
        return "provider-resilience"
    if "command_gap" in kinds or "command_policy_pressure" in tags:
        return "workflow-guardrails"
    if "context_pressure" in kinds or "exploration_loop" in tags:
        return "deep-inspection-stability"
    return "growth-planning"


def ecosystem_bundle_exists(bundle_name: str) -> bool:
    return bundle_name in _BUNDLES


def ecosystem_bundle_catalog() -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for bundle_name, bundle in _BUNDLES.items():
        catalog.append(
            {
                "name": bundle_name,
                "summary": bundle.get("summary", ""),
                "why": bundle.get("why", ""),
                "asset_names": [key.split(":", 1)[1] for key in bundle.get("assets", [])],
            }
        )
    return catalog


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


def _bundle_extra_assets(bundle_name: str, workspace: WorkspaceSnapshot) -> list[dict[str, str]]:
    root = Path(workspace.root)
    assets: list[dict[str, str]] = []
    for asset in _EXTRA_BUNDLE_ASSETS.get(bundle_name, []):
        target = root / str(asset["target_path"])
        if target.exists():
            continue
        assets.append(dict(asset))
    return assets


def _generic_capability_assets(trace: TaskTrace, workspace: WorkspaceSnapshot) -> list[dict[str, str]]:
    capability_gap = dict(trace.artifacts.get("capability_gap", {}) or {})
    capability_name = str(capability_gap.get("name", "") or "workspace capability").strip()
    capability_slug = _normalized_name(capability_name) or "workspace-capability"
    preferred_surfaces = [str(item).strip().lower() for item in capability_gap.get("preferred_surfaces", []) if str(item).strip()]
    if not preferred_surfaces:
        preferred_surfaces = ["plugin", "command", "skill"]
    evidence = [str(item).strip() for item in capability_gap.get("evidence", []) if str(item).strip()]
    evidence_lines = evidence[:3] or [trace.summary]
    root = Path(workspace.root)
    assets: list[dict[str, str]] = []

    def missing(target_path: str) -> bool:
        return not (root / target_path).exists()

    plugin_root = f"plugins/{capability_slug}"
    plugin_name = capability_slug
    workflow_name = f"{capability_slug}-workflow"
    skill_name = f"{capability_slug}-bootstrap"
    agent_name = f"{capability_slug}-operator"

    if "plugin" in preferred_surfaces and missing(f"{plugin_root}/.claude-plugin/plugin.json"):
        assets.append(
            {
                "kind": "plugin",
                "name": f"{plugin_name}-plugin",
                "target_path": f"{plugin_root}/.claude-plugin/plugin.json",
                "content": json.dumps(
                    {
                        "name": plugin_name,
                        "version": "0.1.0",
                        "description": f"Self-evolved capability bundle for {capability_name}.",
                        "enabled_by_default": True,
                        "skills_dir": "skills",
                        "commands_dir": "commands",
                        "agents_dir": "agents",
                        "mcp_file": ".mcp.json",
                        "tags": ["self-evolved", "capability", capability_slug],
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
            }
        )

    if "skill" in preferred_surfaces and missing(f"{plugin_root}/skills/{skill_name}.md"):
        assets.append(
            {
                "kind": "skill",
                "name": skill_name,
                "target_path": f"{plugin_root}/skills/{skill_name}.md",
                "content": "\n".join(
                    [
                        "---",
                        f"name: {skill_name}",
                        f"description: Bootstrap and validate the self-evolved capability for {capability_name}.",
                        "---",
                        "",
                        f"# {capability_name} Bootstrap",
                        "",
                        "- Start by inspecting the current workspace surface before adding more scaffolding.",
                        "- Confirm whether the capability already exists through commands, plugins, MCP, or local tools.",
                        "- If still missing, install or generate only the smallest capability slice needed to unblock the task.",
                        "- End by replaying the blocked task instead of only describing the capability in prose.",
                        "",
                        "## Evidence",
                        *[f"- {line}" for line in evidence_lines],
                        "",
                    ]
                ),
            }
        )

    if "agent" in preferred_surfaces and missing(f"{plugin_root}/agents/{agent_name}.md"):
        assets.append(
            {
                "kind": "agent",
                "name": agent_name,
                "target_path": f"{plugin_root}/agents/{agent_name}.md",
                "content": "\n".join(
                    [
                        "---",
                        f"description: Operate and validate the self-evolved capability for {capability_name}",
                        "tools: workspace_status,list_registry,mcp_registry_detail,mcp_call_tool,read_file,write_file",
                        "parallel-safe: false",
                        "---",
                        "",
                        f"# {capability_name} Operator",
                        "",
                        "- Inspect the current surface first.",
                        "- Prefer real execution and replay over commentary.",
                        "- Finish by stating whether the capability is now actually usable in-session.",
                        "",
                    ]
                ),
            }
        )

    if "command" in preferred_surfaces and missing(f"{plugin_root}/commands/{workflow_name}.md"):
        assets.append(
            {
                "kind": "command",
                "name": workflow_name,
                "target_path": f"{plugin_root}/commands/{workflow_name}.md",
                "content": "\n".join(
                    [
                        "---",
                        f"description: Use the self-evolved capability bundle for {capability_name}",
                        "argument-hint: Task or target path",
                        "allowed-tools: workspace_status,list_registry,tool_help,skill,mcp_registry_detail,mcp_call_tool,read_file,write_file",
                        "---",
                        "",
                        f"# {capability_name} Workflow",
                        "",
                        "Target: $ARGUMENTS",
                        "",
                        f"1. Load `{skill_name}` first.",
                        "2. Inspect whether the capability is already present and sufficient for the target task.",
                        "3. If present, use it directly; if not, report the smallest missing implementation slice.",
                        "4. End by replaying the blocked task and reporting whether it now succeeds.",
                        "",
                    ]
                ),
            }
        )

    if "mcp" in preferred_surfaces and missing(f"{plugin_root}/.mcp.json"):
        server_name = f"{capability_slug}-tools"
        assets.append(
            {
                "kind": "plugin",
                "name": f"{plugin_name}-mcp",
                "target_path": f"{plugin_root}/.mcp.json",
                "content": json.dumps(
                    {
                        "mcpServers": {
                            server_name: {
                                "transport": "stdio",
                                "command": "python",
                                "args": ["-c", "import json; print(json.dumps({'warning': 'implement capability-specific MCP server'}))"],
                                "description": f"Placeholder MCP entry for the self-evolved capability {capability_name}.",
                                "tools": [
                                    {
                                        "name": "inspect_capability_status",
                                        "description": f"Inspect whether {capability_name} is fully implemented.",
                                    }
                                ],
                            }
                        }
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
            }
        )

    return assets


def _normalized_stem(path_str: str) -> str:
    return _normalized_name(Path(path_str).stem)


def _normalized_name(name: str) -> str:
    return name.replace("_", "-").replace(" ", "-").lower()
