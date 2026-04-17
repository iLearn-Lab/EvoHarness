from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from evo_harness.models import CapabilityGrowthPlan, CapabilitySurfaceGraph, TaskRequirementGraph, TaskTrace, WorkspaceSnapshot


_ACTION_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("read-input", (r"\bread\b", r"\binspect\b", r"\bextract\b", r"\bparse\b", r"\bload\b", r"\bingest\b")),
    ("inspect-state", (r"\bcheck\b", r"\binspect\b", r"\baudit\b", r"\btriage\b", r"\bmonitor\b", r"\bdiagnos")),
    ("open-target", (r"\bopen\b", r"\bnavigate\b", r"\bvisit\b", r"\bconnect\b", r"\battach\b")),
    ("query-service", (r"\bquery\b", r"\bfetch\b", r"\brequest\b", r"\bcall\b", r"\bpoll\b", r"\bsearch\b")),
    ("authenticate-session", (r"\bsign in\b", r"\blogin\b", r"\bauthenticate\b", r"\bcredential\b", r"\btoken\b")),
    ("execute-command", (r"\brun\b", r"\bexecute\b", r"\binvoke\b", r"\bdeploy\b", r"\blaunch\b")),
    ("transform-data", (r"\btransform\b", r"\bconvert\b", r"\bnormalize\b", r"\bmap\b", r"\bmerge\b", r"\bfilter\b")),
    ("compare-results", (r"\bcompare\b", r"\bdiff\b", r"\bvalidate\b", r"\bverify\b", r"\bassert\b")),
    ("capture-artifact", (r"\bcapture\b", r"\bscreenshot\b", r"\brecord\b", r"\bexport\b", r"\barchive\b")),
    ("produce-deliverable", (r"\bwrite\b", r"\bgenerate\b", r"\bdraft\b", r"\bcreate\b", r"\bproduce\b", r"\bsave\b")),
    ("apply-change", (r"\bpatch\b", r"\bupdate\b", r"\bmodify\b", r"\bedit\b", r"\bchange\b")),
    ("save-reusable-state", (r"\bpersist\b", r"\bsave\b", r"\bstore\b", r"\bcache\b", r"\bcheckpoint\b")),
    ("load-reusable-state", (r"\brestore\b", r"\breuse\b", r"\bresume\b", r"\brecover\b")),
]

_COMMON_FILLER_TOKENS = {
    "a",
    "an",
    "the",
    "and",
    "for",
    "with",
    "without",
    "into",
    "from",
    "through",
    "using",
    "via",
}

_REUSE_PATTERNS = ("future sessions", "across sessions", "reuse", "reusable", "persistent", "persist")


def build_generic_capability_growth_change_request(
    trace: TaskTrace,
    workspace: WorkspaceSnapshot,
) -> dict[str, Any]:
    requirements = derive_task_requirements(trace)
    surface = inspect_workspace_capability_surface(Path(workspace.root))
    plan = build_capability_growth_plan(requirements, surface)
    replay_contract = build_replay_contract(requirements, plan, trace)
    research_plan = build_capability_research_plan(requirements, plan)
    implementation_contract = build_implementation_contract(
        requirements,
        plan,
        research_plan=research_plan,
        replay_contract=replay_contract,
    )
    scaffold_assets = synthesize_capability_assets(
        requirements=requirements,
        plan=plan,
        replay_contract=replay_contract,
        research_plan=research_plan,
        implementation_contract=implementation_contract,
        workspace_root=Path(workspace.root),
    )
    return {
        "requirement_graph": requirements.to_dict(),
        "surface_graph": surface.to_dict(),
        "capability_plan": plan.to_dict(),
        "replay_contract": replay_contract,
        "research_plan": research_plan,
        "implementation_contract": implementation_contract,
        "scaffold_assets": scaffold_assets,
        "target_files": [asset["target_path"] for asset in scaffold_assets],
    }


def derive_task_requirements(trace: TaskTrace) -> TaskRequirementGraph:
    prompt = str(trace.artifacts.get("initial_user_prompt", "") or "")
    capability_gap = dict(trace.artifacts.get("capability_gap", {}) or {})
    capability_name = str(capability_gap.get("name", "") or "").strip()
    requested_surfaces = _normalized_list(capability_gap.get("preferred_surfaces", []))
    evidence = [str(item).strip() for item in capability_gap.get("evidence", []) if str(item).strip()]
    if not evidence:
        evidence = [trace.summary]

    text = "\n".join(
        [
            prompt,
            trace.summary,
            str(capability_gap.get("name", "") or ""),
            str(trace.artifacts.get("replay_prompt", "") or ""),
            "\n".join(evidence),
            "\n".join(trace.error_tags),
        ]
    ).strip()
    lowered = text.lower()

    ai_inputs = _normalized_list(capability_gap.get("inputs", []))
    ai_outputs = _normalized_list(capability_gap.get("outputs", []))
    ai_actions = _normalized_list(capability_gap.get("workflow_actions", []))
    ai_states = _normalized_list(capability_gap.get("state_targets", []))
    ai_dependencies = _normalized_list(capability_gap.get("dependencies", []))
    ai_constraints = _normalized_list(capability_gap.get("constraints", []))
    ai_domains = [_normalized_name(item) for item in _normalized_list(capability_gap.get("domain_tags", []))]
    ai_growth_units = _normalized_list(capability_gap.get("growth_units", []))
    ai_research_plan = dict(capability_gap.get("research_plan", {}) or {}) if isinstance(capability_gap.get("research_plan"), dict) else {}
    ai_implementation_contract = _normalized_contract(capability_gap.get("implementation_contract"))
    ai_replay_contract = _normalized_contract(capability_gap.get("replay_contract"))
    if not requested_surfaces:
        requested_surfaces = _normalized_list(ai_implementation_contract.get("primary_entrypoints", []))
    if not ai_growth_units:
        ai_growth_units = _normalized_list(ai_implementation_contract.get("primary_entrypoints", []))

    domain_tags = ai_domains or _derive_domain_tags(text, capability_name, ai_inputs, ai_outputs, ai_dependencies)
    input_objects = ai_inputs or _derive_input_objects(text)
    input_formats = _derive_input_formats(lowered)
    deliverables = ai_outputs or _derive_deliverables(text, input_formats)
    workflow_actions = ai_actions or _derive_workflow_actions(lowered, deliverables, input_objects)
    state_targets = ai_states or _derive_state_targets(text, workflow_actions, capability_name)
    reuse_across_sessions = any(phrase in lowered for phrase in _REUSE_PATTERNS) or bool(state_targets)
    external_dependencies = _normalize_dependency_labels(
        ai_dependencies or _derive_external_dependencies(text, input_objects, workflow_actions, state_targets),
        text=text,
    )
    environment_targets = _derive_environment_targets(domain_tags, external_dependencies, input_objects)
    constraints = _unique([*ai_constraints, *_derive_constraints(lowered)])

    if not capability_name:
        capability_name = _default_capability_name(domain_tags, input_objects, deliverables, workflow_actions)
    capability_name = _canonical_capability_name(
        capability_name,
        input_objects=input_objects,
        deliverables=deliverables,
        workflow_actions=workflow_actions,
    )
    operation_specs = _derive_operation_specs(
        workflow_actions,
        deliverables,
        input_objects,
        state_targets,
        capability_gap.get("validation_targets", []),
    )

    return TaskRequirementGraph(
        capability_name=capability_name,
        input_objects=input_objects,
        input_formats=input_formats,
        environment_targets=environment_targets,
        deliverables=deliverables,
        workflow_actions=workflow_actions,
        requested_surfaces=requested_surfaces,
        requested_growth_unit=ai_growth_units,
        domain_tags=domain_tags,
        state_targets=state_targets,
        operation_specs=operation_specs,
        reuse_across_sessions=reuse_across_sessions,
        external_dependencies=external_dependencies,
        constraints=constraints,
        evidence=evidence[:5],
        research_plan=ai_research_plan,
        implementation_contract=ai_implementation_contract,
        replay_contract=ai_replay_contract,
    )


def inspect_workspace_capability_surface(workspace_root: Path) -> CapabilitySurfaceGraph:
    commands = _workspace_markdown_asset_names(workspace_root, "commands")
    skills = _workspace_markdown_asset_names(workspace_root, "skills")
    agents = _workspace_markdown_asset_names(workspace_root, "agents")
    plugins = _plugin_names_from_fs(workspace_root)
    mcp_servers = _mcp_server_names_from_fs(workspace_root)
    dependency_markers = _dependency_markers(workspace_root)
    return CapabilitySurfaceGraph(
        commands=commands,
        skills=skills,
        agents=agents,
        plugins=plugins,
        mcp_servers=mcp_servers,
        dependency_markers=dependency_markers,
        counts={
            "commands": len(commands),
            "skills": len(skills),
            "agents": len(agents),
            "plugins": len(plugins),
            "mcp_servers": len(mcp_servers),
            "dependency_markers": len(dependency_markers),
        },
    )


def build_capability_growth_plan(
    requirements: TaskRequirementGraph,
    surface: CapabilitySurfaceGraph,
) -> CapabilityGrowthPlan:
    capability_slug = _normalized_name(requirements.capability_name) or "workspace-capability"
    surface_kind = _effective_surface_kind(requirements)
    preferred_surfaces = _preferred_surfaces(requirements)
    capability_keywords = _capability_keywords(requirements, capability_slug)

    gap_types: list[str] = []
    for surface_name in preferred_surfaces:
        if not _surface_group_mentions_capability(surface, surface_name, capability_keywords):
            gap_types.append(surface_name)

    if requirements.reuse_across_sessions or len(requirements.operation_specs) >= 3:
        gap_types.append("workflow_glue")

    dependency_keywords = _dependency_keywords(requirements)
    if dependency_keywords and not any(
        keyword in marker
        for keyword in dependency_keywords
        for marker in surface.dependency_markers
    ):
        gap_types.append("dependency")

    if any(item in {"credentials", "account-session"} for item in requirements.external_dependencies):
        gap_types.append("credential_handling")

    if any(item not in {"filesystem-access", "credentials", "account-session"} for item in requirements.external_dependencies):
        gap_types.append("external_infrastructure")

    gap_types = _unique(gap_types)

    if requirements.requested_growth_unit:
        minimal_growth_unit = _unique(list(requirements.requested_growth_unit))
    else:
        minimal_growth_unit = []
        if "plugin" in gap_types or requirements.reuse_across_sessions:
            minimal_growth_unit.append("plugin")
        if surface_kind in {"executable", "mixed"} and ("mcp" in gap_types or _requires_mcp_surface(requirements)):
            minimal_growth_unit.append("mcp")
        if "workflow_glue" in gap_types:
            minimal_growth_unit.extend(["skill", "command"])
        if surface_kind in {"executable", "mixed"} and (len(requirements.operation_specs) >= 4 or "agent" in gap_types):
            minimal_growth_unit.append("agent")
        if surface_kind in {"executable", "mixed"} and {"dependency", "credential_handling", "external_infrastructure"} & set(gap_types):
            minimal_growth_unit.append("bootstrap")
        minimal_growth_unit = _unique(minimal_growth_unit)

    return CapabilityGrowthPlan(
        capability_name=requirements.capability_name,
        capability_slug=capability_slug,
        gap_types=gap_types,
        minimal_growth_unit=minimal_growth_unit,
        preferred_surfaces=preferred_surfaces,
        required_assets=_required_assets_from_growth_unit(minimal_growth_unit),
        dependency_hints=_dependency_hints(requirements, gap_types),
        validation_hints=_validation_hints(requirements),
        workflow_outline=_workflow_outline(requirements),
        synthesis_notes=[
            "Prefer the smallest reusable capability slice that can be replayed in-session.",
            "Expose persistent surfaces before relying on one-off shell commands.",
            "Keep credential handling and external dependencies explicit in the synthesized bundle.",
        ],
    )


def build_replay_contract(
    requirements: TaskRequirementGraph,
    plan: CapabilityGrowthPlan,
    trace: TaskTrace,
) -> dict[str, Any]:
    success_signals = list(requirements.deliverables)
    success_signals.extend(
        signal
        for signal in (
            "cross-session-reuse" if requirements.reuse_across_sessions else "",
            "real-execution" if "real-execution" in requirements.constraints else "",
            "no-capability-gap-on-replay",
        )
        if signal
    )
    fallback = {
        "original_prompt": str(
            trace.artifacts.get("replay_prompt")
            or trace.artifacts.get("initial_user_prompt")
            or ""
        ).strip(),
        "max_refinement_rounds": 2,
        "success_signals": _unique(success_signals),
        "failure_signals": [
            "missing-capability-surface",
            "placeholder-only-implementation",
            "replay-still-requests-grow-ecosystem",
        ],
        "required_growth_unit": list(plan.minimal_growth_unit),
        "validation_hints": list(plan.validation_hints),
    }
    if not requirements.replay_contract:
        return fallback

    replay_contract = dict(requirements.replay_contract)
    merged = dict(fallback)
    original_prompt = str(replay_contract.get("original_prompt", "") or "").strip()
    if original_prompt:
        merged["original_prompt"] = original_prompt
    success = _normalized_list(replay_contract.get("success_signals", []))
    if success:
        merged["success_signals"] = _unique([*success, *fallback["success_signals"]])
    failure = _normalized_list(replay_contract.get("failure_signals", []))
    if failure:
        merged["failure_signals"] = _unique(failure)
    validation_hints = _normalized_list(replay_contract.get("validation_hints", []))
    if validation_hints:
        merged["validation_hints"] = _unique([*validation_hints, *fallback["validation_hints"]])
    preferred_entrypoints = _normalized_list(replay_contract.get("preferred_entrypoints", []))
    if preferred_entrypoints:
        merged["preferred_entrypoints"] = preferred_entrypoints
    required_growth_unit = _normalized_list(replay_contract.get("required_growth_unit", []))
    if required_growth_unit:
        merged["required_growth_unit"] = required_growth_unit
    try:
        merged["max_refinement_rounds"] = max(
            0,
            int(replay_contract.get("max_refinement_rounds", fallback["max_refinement_rounds"]) or 0),
        )
    except Exception:
        merged["max_refinement_rounds"] = fallback["max_refinement_rounds"]
    notes = _normalized_list(replay_contract.get("notes", []))
    if notes:
        merged["notes"] = notes
    return merged


def build_implementation_contract(
    requirements: TaskRequirementGraph,
    plan: CapabilityGrowthPlan,
    *,
    research_plan: dict[str, Any],
    replay_contract: dict[str, Any],
) -> dict[str, Any]:
    inferred_surface_kind = (
        "executable"
        if _requires_mcp_surface(requirements)
        or any(item not in {"filesystem-access"} for item in requirements.external_dependencies)
        else "instructional"
    )
    fallback = {
        "surface_kind": inferred_surface_kind,
        "summary": (
            f"Implement the smallest reusable {requirements.capability_name} surface that satisfies the replay contract."
        ),
        "primary_entrypoints": list(plan.minimal_growth_unit),
        "runtime_dependencies": _contract_runtime_dependencies(requirements),
        "concrete_operations": list(_workflow_outline(requirements)),
        "state_artifacts": list(requirements.state_targets),
        "deliverable_paths": list(requirements.deliverables),
        "validation_steps": _unique(
            [
                *[str(item) for item in replay_contract.get("validation_hints", [])],
                *[str(item) for item in plan.dependency_hints],
            ]
        ),
        "notes": _unique(
            [
                *plan.synthesis_notes,
                *[str(item) for item in research_plan.get("implementation_checkpoints", [])],
            ]
        )[:8],
    }
    if not requirements.implementation_contract:
        return fallback

    contract = dict(requirements.implementation_contract)
    merged = dict(fallback)
    surface_kind = _normalized_surface_kind(contract.get("surface_kind"))
    if surface_kind:
        merged["surface_kind"] = surface_kind
    summary = str(contract.get("summary", "") or "").strip()
    if summary:
        merged["summary"] = summary
    for key in (
        "primary_entrypoints",
        "runtime_dependencies",
        "concrete_operations",
        "state_artifacts",
        "deliverable_paths",
        "validation_steps",
        "notes",
    ):
        values = _normalized_list(contract.get(key, []))
        if values:
            merged[key] = values
    return merged


def build_capability_research_plan(
    requirements: TaskRequirementGraph,
    plan: CapabilityGrowthPlan,
) -> dict[str, Any]:
    if requirements.research_plan:
        research_plan = dict(requirements.research_plan)
        research_plan["research_needed"] = bool(
            research_plan.get("research_needed", True)
            or {"dependency", "external_infrastructure", "credential_handling"} & set(plan.gap_types)
            or len(requirements.operation_specs) >= 3
        )
        for key in ("search_queries", "implementation_checkpoints", "source_preferences", "selection_criteria"):
            values = [str(item).strip() for item in research_plan.get(key, []) if str(item).strip()]
            if values:
                research_plan[key] = _unique(values)
        return research_plan
    research_needed = bool(
        {"dependency", "external_infrastructure", "credential_handling"} & set(plan.gap_types)
        or len(requirements.operation_specs) >= 3
        or any(dep not in {"filesystem-access"} for dep in requirements.external_dependencies)
    )
    capability_text = requirements.capability_name.replace("-", " ").strip() or "requested capability"
    queries = [
        f"{capability_text} official documentation",
        f"{capability_text} implementation example",
    ]
    if requirements.domain_tags:
        queries.append(f"{' '.join(requirements.domain_tags[:3]).replace('-', ' ')} official documentation")
    if requirements.deliverables:
        queries.append(f"{capability_text} {' '.join(requirements.deliverables[:2])} example")
    if requirements.workflow_actions:
        queries.append(f"{capability_text} {' '.join(requirements.workflow_actions[:3])} workflow")
    for dependency in requirements.external_dependencies:
        if dependency in {"filesystem-access", "account-session"}:
            continue
        dependency_text = dependency.replace("-", " ")
        queries.append(f"{dependency_text} python integration")
    implementation_checkpoints = [
        "Identify at least one official or reference implementation path before choosing a stack.",
        "Select the smallest dependency and runtime surface that can satisfy the replay contract.",
        "Record the chosen stack and why it beats the next-best alternative.",
        "Turn the resulting workflow into durable plugin, command, skill, and MCP surfaces.",
    ]
    if requirements.state_targets:
        implementation_checkpoints.append("Make reusable state explicit and document how it is saved, loaded, and invalidated.")
    return {
        "research_needed": research_needed,
        "source_preferences": [
            "official product or library documentation",
            "reference implementations or canonical examples",
            "SDK or API docs with executable examples",
            "implementation notes that include setup, limits, and failure modes",
        ],
        "search_queries": _unique([query.strip() for query in queries if query.strip()])[:8],
        "implementation_checkpoints": implementation_checkpoints,
        "selection_criteria": [
            "Prefer the path with the fewest moving parts that still satisfies replay.",
            "Prefer sources that describe real execution steps over conceptual summaries.",
            "Avoid adding dependencies that do not materially improve the replay contract.",
        ],
    }


def synthesize_capability_assets(
    *,
    requirements: TaskRequirementGraph,
    plan: CapabilityGrowthPlan,
    replay_contract: dict[str, Any],
    research_plan: dict[str, Any],
    implementation_contract: dict[str, Any],
    workspace_root: Path,
) -> list[dict[str, str]]:
    plugin_root = f"plugins/{plan.capability_slug}"
    skill_name = f"{plan.capability_slug}-bootstrap"
    agent_name = f"{plan.capability_slug}-operator"
    command_name = f"{plan.capability_slug}-workflow"
    server_name = f"{plan.capability_slug}-tools"
    implementation_script_paths = _implementation_script_target_paths(
        requirements,
        plan,
        implementation_contract,
    )
    assets: list[dict[str, str]] = []

    def missing(target_path: str) -> bool:
        return not (workspace_root / target_path).exists()

    if "plugin-manifest" in plan.required_assets and missing(f"{plugin_root}/.claude-plugin/plugin.json"):
        assets.append(
            {
                "kind": "plugin",
                "name": f"{plan.capability_slug}-plugin",
                "target_path": f"{plugin_root}/.claude-plugin/plugin.json",
                "content": json.dumps(
                    {
                        "name": plan.capability_slug,
                        "version": "0.1.0",
                        "description": f"Self-evolved reusable capability bundle for {requirements.capability_name}.",
                        "enabled_by_default": True,
                        "skills_dir": "skills",
                        "commands_dir": "commands",
                        "agents_dir": "agents",
                        "mcp_file": ".mcp.json",
                        "tags": ["self-evolved", "capability", plan.capability_slug, *plan.gap_types],
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
            }
        )

    if "skill" in plan.required_assets and missing(f"{plugin_root}/skills/{skill_name}.md"):
        assets.append(
            {
                "kind": "skill",
                "name": skill_name,
                "target_path": f"{plugin_root}/skills/{skill_name}.md",
                "content": "\n".join(
                    [
                        "---",
                        f"name: {skill_name}",
                        f"description: Bootstrap, inspect, and replay the {requirements.capability_name} capability.",
                        "---",
                        "",
                        f"# {requirements.capability_name} Bootstrap",
                        "",
                        "- Start from the current workspace surface rather than assuming the capability exists.",
                        "- If the implementation path is unclear, research the capability before coding and record the chosen stack.",
                        "- Confirm the missing surfaces listed in the capability plan before adding more code.",
                        "- Implement only the minimal growth unit needed for a successful replay.",
                        "- End by replaying the blocked task and checking the replay contract.",
                        "",
                        "## Implementation Contract",
                        f"- summary: {implementation_contract.get('summary', '')}",
                        *[f"- entrypoint: {line}" for line in implementation_contract.get("primary_entrypoints", [])],
                        *[f"- operation: {line}" for line in implementation_contract.get("concrete_operations", [])],
                        *[f"- script: {line}" for line in implementation_script_paths],
                        "",
                        "## Research Queries",
                        *[f"- {line}" for line in research_plan.get("search_queries", [])],
                        "",
                        "## Workflow Outline",
                        *[f"- {line}" for line in plan.workflow_outline],
                        "",
                        "## Validation Hints",
                        *[f"- {line}" for line in plan.validation_hints],
                        "",
                    ]
                ),
            }
        )

    if "agent" in plan.required_assets and missing(f"{plugin_root}/agents/{agent_name}.md"):
        assets.append(
            {
                "kind": "agent",
                "name": agent_name,
                "target_path": f"{plugin_root}/agents/{agent_name}.md",
                "content": "\n".join(
                    [
                        "---",
                        f"description: Operate and validate the self-evolved {requirements.capability_name} workflow",
                        "tools: workspace_status,list_registry,mcp_registry_detail,mcp_call_tool,read_file,write_file,bash",
                        "parallel-safe: false",
                        "---",
                        "",
                        f"# {requirements.capability_name} Operator",
                        "",
                        "- Inspect the workspace surface before attempting implementation.",
                        "- If the capability is unfamiliar, search for official docs and reference implementations first.",
                        "- Prefer real tool execution and replay over narrative descriptions.",
                        "- Report whether the capability is now usable across fresh sessions.",
                        "",
                    ]
                ),
            }
        )

    if "command" in plan.required_assets and missing(f"{plugin_root}/commands/{command_name}.md"):
        assets.append(
            {
                "kind": "command",
                "name": command_name,
                "target_path": f"{plugin_root}/commands/{command_name}.md",
                "content": "\n".join(
                    [
                        "---",
                        f"description: Run the reusable {requirements.capability_name} workflow",
                        "argument-hint: Task, URL, or input path",
                        "allowed-tools: workspace_status,list_registry,tool_help,skill,mcp_registry_detail,mcp_call_tool,read_file,write_file,bash",
                        "---",
                        "",
                        f"# {requirements.capability_name} Workflow",
                        "",
                        "Target: $ARGUMENTS",
                        "",
                        f"1. Load `{skill_name}` first.",
                        "2. Inspect whether the required plugin, MCP, and workflow surfaces are present.",
                        *[f"- Prefer entrypoint: {line}" for line in implementation_contract.get("primary_entrypoints", [])[:3]],
                        *[f"- Prefer implementation script: {line}" for line in implementation_script_paths[:2]],
                        "3. If support is missing or unclear, research the implementation path before selecting a stack.",
                        "4. Execute the minimum workflow needed to satisfy the replay contract.",
                        "5. End by stating whether the capability now works in a fresh session.",
                        "",
                    ]
                ),
            }
        )

    if "mcp-server" in plan.required_assets and missing(f"{plugin_root}/.mcp.json"):
        assets.append(
            {
                "kind": "plugin",
                "name": f"{plan.capability_slug}-mcp",
                "target_path": f"{plugin_root}/.mcp.json",
                "content": json.dumps(
                    {
                        "mcpServers": {
                            server_name: {
                                "transport": "stdio",
                                "command": "python",
                                "args": [f"{plugin_root}/server.py"],
                                "description": f"Executable MCP server template for the self-evolved capability {requirements.capability_name}.",
                                "tools": _mcp_tool_specs(requirements),
                                "prompts": [
                                    {
                                        "name": "replay_capability_task",
                                        "description": f"Replay a blocked task through the {requirements.capability_name} workflow.",
                                    }
                                ],
                            },
                            **(
                                {
                                    "capability-research": {
                                        "transport": "stdio",
                                        "command": "python",
                                        "args": ["-m", "evo_harness.web_research_mcp_server"],
                                        "description": f"Public web research sidecar for self-evolving the capability {requirements.capability_name}.",
                                    }
                                }
                                if research_plan.get("research_needed")
                                else {}
                            ),
                        }
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
            }
        )

    if "server-script" in plan.required_assets and missing(f"{plugin_root}/server.py"):
        assets.append(
            {
                "kind": "script",
                "name": f"{plan.capability_slug}-server",
                "target_path": f"{plugin_root}/server.py",
                "content": _server_script_content(requirements, plan),
            }
        )

    for script_path in implementation_script_paths:
        if not missing(script_path):
            continue
        assets.append(
            {
                "kind": "script",
                "name": Path(script_path).stem,
                "target_path": script_path,
                "content": _implementation_script_content(
                    requirements,
                    plan,
                    implementation_contract,
                    target_path=script_path,
                ),
            }
        )

    if "plan-doc" in plan.required_assets and missing(f"{plugin_root}/docs/capability-plan.json"):
        assets.append(
            {
                "kind": "doc",
                "name": f"{plan.capability_slug}-plan",
                "target_path": f"{plugin_root}/docs/capability-plan.json",
                "content": json.dumps(
                    {
                        "requirement_graph": requirements.to_dict(),
                        "capability_plan": plan.to_dict(),
                        "research_plan": research_plan,
                        "implementation_contract": implementation_contract,
                        "replay_contract": replay_contract,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
            }
        )

    if "requirements-file" in plan.required_assets and missing(f"{plugin_root}/requirements.txt"):
        assets.append(
            {
                "kind": "doc",
                "name": f"{plan.capability_slug}-requirements",
                "target_path": f"{plugin_root}/requirements.txt",
                "content": _requirements_file_content(requirements),
            }
        )

    if "bootstrap-guide" in plan.required_assets and missing(f"{plugin_root}/docs/bootstrap-checklist.md"):
        assets.append(
            {
                "kind": "doc",
                "name": f"{plan.capability_slug}-bootstrap-checklist",
                "target_path": f"{plugin_root}/docs/bootstrap-checklist.md",
                "content": "\n".join(
                    [
                        f"# {requirements.capability_name} Bootstrap Checklist",
                        "",
                        "## Research Plan",
                        *[f"- query: {line}" for line in research_plan.get("search_queries", [])],
                        *[f"- checkpoint: {line}" for line in research_plan.get("implementation_checkpoints", [])],
                        "",
                        "## Implementation Contract",
                        f"- summary: {implementation_contract.get('summary', '')}",
                        *[f"- entrypoint: {line}" for line in implementation_contract.get("primary_entrypoints", [])],
                        *[f"- dependency: {line}" for line in implementation_contract.get("runtime_dependencies", [])],
                        *[f"- operation: {line}" for line in implementation_contract.get("concrete_operations", [])],
                        *[f"- validate: {line}" for line in implementation_contract.get("validation_steps", [])],
                        "",
                        "## Dependency Hints",
                        *[f"- {line}" for line in plan.dependency_hints],
                        "",
                        "## Replay Contract",
                        *[f"- success: {line}" for line in replay_contract.get("success_signals", [])],
                        *[f"- failure: {line}" for line in replay_contract.get("failure_signals", [])],
                        "",
                    ]
                ),
            }
        )

    if "verification-script" in plan.required_assets and missing(f"{plugin_root}/scripts/verify_{plan.capability_slug.replace('-', '_')}.py"):
        assets.append(
            {
                "kind": "script",
                "name": f"verify-{plan.capability_slug}",
                "target_path": f"{plugin_root}/scripts/verify_{plan.capability_slug.replace('-', '_')}.py",
                "content": "\n".join(
                    [
                        "from __future__ import annotations",
                        "",
                        "import json",
                        "from pathlib import Path",
                        "",
                        "",
                        "def main() -> None:",
                        "    workspace = Path.cwd()",
                        "    payload = {",
                        f"        'capability': {json.dumps(requirements.capability_name)},",
                        f"        'expected_surfaces': {json.dumps(plan.minimal_growth_unit, ensure_ascii=False)},",
                        f"        'success_signals': {json.dumps(replay_contract.get('success_signals', []), ensure_ascii=False)},",
                        f"        'research_queries': {json.dumps(research_plan.get('search_queries', []), ensure_ascii=False)},",
                        f"        'implementation_contract': {json.dumps(implementation_contract, ensure_ascii=False)},",
                        "        'status': 'research-ready',",
                        "        'workspace': str(workspace),",
                        "    }",
                        "    print(json.dumps(payload, ensure_ascii=False))",
                        "",
                        "",
                        "if __name__ == '__main__':",
                        "    main()",
                        "",
                    ]
                ),
            }
        )

    return assets


def _normalized_list(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _normalized_contract(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key, value in raw.items():
        normalized_key = str(key).strip()
        if not normalized_key:
            continue
        if isinstance(value, dict):
            nested = _normalized_contract(value)
            if nested:
                normalized[normalized_key] = nested
            continue
        if isinstance(value, list):
            values = [str(item).strip() for item in value if str(item).strip()]
            if values:
                normalized[normalized_key] = values
            continue
        if isinstance(value, bool):
            normalized[normalized_key] = value
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            normalized[normalized_key] = value
            continue
        text = str(value).strip()
        if text:
            normalized[normalized_key] = text
    return normalized


def _normalized_surface_kind(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"instructional", "executable", "mixed"}:
        return normalized
    return ""


def _implementation_surface_kind(contract: dict[str, Any]) -> str:
    return _normalized_surface_kind(contract.get("surface_kind")) or "instructional"


def _effective_surface_kind(requirements: TaskRequirementGraph) -> str:
    explicit = _normalized_surface_kind(requirements.implementation_contract.get("surface_kind"))
    if explicit:
        return explicit
    deliverable_paths = _normalized_list(requirements.implementation_contract.get("deliverable_paths", []))
    if any(
        path.endswith(".py") or path.endswith(".sh") or path.endswith(".ps1") or path.endswith(".mcp.json")
        for path in deliverable_paths
    ):
        return "executable"
    if {"mcp", "agent"} & set(requirements.requested_surfaces):
        return "executable"
    if {"mcp", "agent", "bootstrap"} & set(requirements.requested_growth_unit):
        return "executable"
    if _requires_mcp_surface(requirements):
        return "executable"
    if any(item not in {"filesystem-access"} for item in requirements.external_dependencies):
        return "executable"
    return "instructional"


def _contract_runtime_dependencies(requirements: TaskRequirementGraph) -> list[str]:
    dependencies = [
        item
        for item in [*requirements.input_objects, *requirements.external_dependencies]
        if str(item).strip() and str(item).strip().lower() not in {"filesystem-access"}
    ]
    return _unique([str(item).strip() for item in dependencies if str(item).strip()])


def _derive_domain_tags(
    text: str,
    capability_name: str,
    input_objects: list[str],
    deliverables: list[str],
    dependencies: list[str],
) -> list[str]:
    tokens: list[str] = []
    for source in [capability_name, *input_objects, *deliverables, *dependencies]:
        tokens.extend(_meaningful_tokens(str(source)))
    if not tokens:
        tokens.extend(_meaningful_tokens(text)[:6])
    return _unique(tokens[:8])


def _derive_input_objects(text: str) -> list[str]:
    objects = [
        match.group(0)
        for match in re.finditer(r"[\w./:-]+\.(?:md|docx|doc|pdf|txt|json|csv|yaml|yml|xml|html|png|jpg|jpeg)", text, re.IGNORECASE)
    ]
    objects.extend(match.group(0) for match in re.finditer(r"https?://[^\s)]+", text, re.IGNORECASE))
    objects.extend(_quoted_spans(text))
    return _unique(objects[:8])


def _derive_input_formats(lowered: str) -> list[str]:
    formats = []
    extension_map = {
        ".md": "markdown",
        ".docx": "docx",
        ".doc": "doc",
        ".pdf": "pdf",
        ".json": "json",
        ".csv": "csv",
        ".txt": "text",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".xml": "xml",
        ".html": "html",
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
    }
    for suffix, name in extension_map.items():
        if suffix in lowered:
            formats.append(name)
    if "http://" in lowered or "https://" in lowered:
        formats.append("url")
    if "word" in lowered and "docx" not in formats:
        formats.append("docx")
    return _unique(formats)


def _derive_environment_targets(
    domain_tags: list[str],
    dependencies: list[str],
    input_objects: list[str],
) -> list[str]:
    targets = ["filesystem"]
    targets.extend(_normalized_name(item) for item in domain_tags[:4])
    targets.extend(_normalized_name(item) for item in dependencies if "filesystem" not in str(item).lower())
    if any(item.startswith("http://") or item.startswith("https://") for item in input_objects):
        targets.append("network")
    return _unique(targets)


def _derive_deliverables(text: str, input_formats: list[str]) -> list[str]:
    lowered = text.lower()
    deliverables: list[str] = []
    for phrase in _collect_following_phrases(text, ("output", "outputs", "artifact", "artifacts", "report", "reports", "summary", "summaries")):
        deliverables.append(_normalized_name(phrase))
    if "screenshot" in lowered:
        deliverables.append("screenshot")
    if any(fmt in {"json", "yaml", "xml", "csv"} for fmt in input_formats):
        deliverables.append("structured-output")
    if "write" in lowered or "save" in lowered or "generate" in lowered:
        deliverables.append("saved-artifact")
    return _unique(deliverables[:8])


def _derive_workflow_actions(lowered: str, deliverables: list[str], input_objects: list[str]) -> list[str]:
    actions: list[str] = []
    for action_name, patterns in _ACTION_PATTERNS:
        if any(re.search(pattern, lowered) for pattern in patterns):
            actions.append(action_name)
    if any(item.startswith("http://") or item.startswith("https://") for item in input_objects) and "open-target" not in actions:
        actions.append("open-target")
    if any(token in lowered for token in ("api", "query", "fetch", "request", "endpoint", "search")) and "query-service" not in actions:
        actions.append("query-service")
    if any(token in lowered for token in ("command", "shell", "bash", "powershell", "kubectl", "git", "run", "execute")) and "execute-command" not in actions:
        actions.append("execute-command")
    if any("screenshot" in item or "artifact" in item for item in deliverables):
        actions.append("capture-artifact")
    if deliverables and "produce-deliverable" not in actions:
        actions.append("produce-deliverable")
    return _unique(actions)


def _derive_state_targets(text: str, workflow_actions: list[str], capability_name: str) -> list[str]:
    state_targets: list[str] = []
    for phrase in _collect_following_phrases(text, ("state", "session", "cache", "checkpoint", "profile", "config", "credentials")):
        state_targets.append(_normalized_name(phrase))
    if "save-reusable-state" in workflow_actions or "load-reusable-state" in workflow_actions:
        fallback = _normalized_name(capability_name) or "capability-state"
        state_targets.append(fallback)
    return _unique(state_targets)


def _derive_operation_specs(
    workflow_actions: list[str],
    deliverables: list[str],
    input_objects: list[str],
    state_targets: list[str],
    validation_targets: Any,
) -> list[dict[str, str]]:
    descriptions = {
        "read-input": "Read or ingest the task inputs into a reusable workflow context.",
        "inspect-state": "Inspect current runtime state, prerequisites, and environmental health.",
        "open-target": "Open or connect to the target system and wait for a usable state.",
        "query-service": "Query the external or local service surface needed by the task.",
        "authenticate-session": "Authenticate with explicit boundaries for credentials and session handling.",
        "execute-command": "Execute the concrete tool, command, or control-plane action required by the workflow.",
        "transform-data": "Transform intermediate data into the structure needed by downstream steps.",
        "compare-results": "Compare, verify, or validate the results against the requested success criteria.",
        "capture-artifact": "Capture the required output artifact, evidence, or snapshot.",
        "produce-deliverable": "Write the final deliverable through a persistent workspace-facing surface.",
        "apply-change": "Apply the requested change to the target environment or artifact set.",
        "save-reusable-state": "Persist the smallest reusable state that future sessions should not rediscover.",
        "load-reusable-state": "Restore reusable state before repeating the workflow.",
    }
    operation_specs = [
        {"name": action_name, "summary": descriptions.get(action_name, action_name.replace("-", " ").capitalize())}
        for action_name in workflow_actions
    ]
    if not operation_specs and deliverables:
        operation_specs.append(
            {"name": "produce-deliverable", "summary": "Produce the requested deliverable through a reusable workflow surface."}
        )
    if state_targets and not any(item["name"] == "save-reusable-state" for item in operation_specs):
        operation_specs.append(
            {"name": "save-reusable-state", "summary": "Persist reusable runtime state for later sessions."}
        )
    if (input_objects or validation_targets) and not any(item["name"] == "inspect-state" for item in operation_specs):
        operation_specs.insert(
            0,
            {"name": "inspect-state", "summary": "Inspect capability prerequisites and current workspace support before execution."},
        )
    return _unique_operation_specs(operation_specs)


def _derive_external_dependencies(
    text: str,
    input_objects: list[str],
    workflow_actions: list[str],
    state_targets: list[str],
) -> list[str]:
    lowered = text.lower()
    dependencies = ["filesystem-access"]
    if any(item.startswith("http://") or item.startswith("https://") for item in input_objects):
        dependencies.append("network-access")
    for token in _meaningful_tokens(text):
        if token not in dependencies:
            dependencies.append(token)
    if any(token in lowered for token in ("credential", "secret", "token", "password", "login", "authenticate", "authentication", "sign in", "signing in", "signin", "account")) or any(
        "credential" in item for item in state_targets
    ):
        dependencies.extend(["credentials", "account-session"])
    if "query-service" in workflow_actions and "network-access" not in dependencies:
        dependencies.append("network-access")
    return _unique(dependencies)


def _derive_constraints(lowered: str) -> list[str]:
    constraints = []
    if any(token in lowered for token in ("truly", "real capability", "real execution", "do not pretend", "really")):
        constraints.append("real-execution")
    if any(token in lowered for token in ("future sessions", "across sessions", "persistent", "reuse")):
        constraints.append("cross-session-reuse")
    if "minimal" in lowered or "smallest" in lowered:
        constraints.append("minimal-growth")
    return _unique(constraints)


def _default_capability_name(
    domain_tags: list[str],
    input_objects: list[str],
    deliverables: list[str],
    workflow_actions: list[str],
) -> str:
    seeds = [*domain_tags, *deliverables, *workflow_actions, *input_objects]
    words = []
    for item in seeds:
        words.extend(_meaningful_tokens(item))
    if words:
        return _normalized_name("-".join(words[:4])) or "workspace-capability"
    return "workspace-capability"


def _canonical_capability_name(
    capability_name: str,
    *,
    input_objects: list[str],
    deliverables: list[str],
    workflow_actions: list[str],
) -> str:
    normalized = _normalized_name(capability_name)
    normalized = re.sub(r"-(with|using|via|plus)-[a-z0-9-]+$", "", normalized)
    if normalized:
        return normalized
    return _default_capability_name([], input_objects, deliverables, workflow_actions)


def _preferred_surfaces(requirements: TaskRequirementGraph) -> list[str]:
    surface_kind = _effective_surface_kind(requirements)
    surfaces: list[str] = []
    surfaces.extend(requirements.requested_surfaces)
    if requirements.reuse_across_sessions or requirements.state_targets:
        surfaces.append("plugin")
    if requirements.workflow_actions or len(requirements.operation_specs) >= 2:
        surfaces.extend(["skill", "command"])
    if surface_kind in {"executable", "mixed"} and _requires_mcp_surface(requirements):
        surfaces.append("mcp")
    if surface_kind in {"executable", "mixed"} and (len(requirements.operation_specs) >= 3 or any(
        action in {"query-service", "execute-command", "authenticate-session", "apply-change"}
        for action in requirements.workflow_actions
    )):
        surfaces.append("agent")
    if not surfaces:
        surfaces.extend(["skill", "command"])
    return _unique(surfaces)


def _required_assets_from_growth_unit(minimal_growth_unit: list[str]) -> list[str]:
    assets = ["plan-doc", "verification-script"]
    if minimal_growth_unit:
        assets.append("plugin-manifest")
    if "skill" in minimal_growth_unit:
        assets.append("skill")
    if "command" in minimal_growth_unit:
        assets.append("command")
    if "agent" in minimal_growth_unit:
        assets.append("agent")
    if "mcp" in minimal_growth_unit:
        assets.append("mcp-server")
        assets.append("server-script")
    if "bootstrap" in minimal_growth_unit:
        assets.append("bootstrap-guide")
        assets.append("requirements-file")
    return _unique(assets)


def _dependency_hints(requirements: TaskRequirementGraph, gap_types: list[str]) -> list[str]:
    hints: list[str] = []
    dependency_labels = [item for item in requirements.external_dependencies if item not in {"filesystem-access", "credentials", "account-session"}]
    if dependency_labels:
        hints.append(
            "Record how to acquire, configure, and smoke-test these dependencies before replay: "
            + ", ".join(dependency_labels[:6])
            + "."
        )
    if requirements.state_targets:
        hints.append("Make reusable state explicit and keep its storage path and invalidation rules documented.")
    if "credentials" in requirements.external_dependencies or "credential_handling" in gap_types:
        hints.append("Define how credentials or authenticated session state are passed and stored safely.")
    if "external_infrastructure" in gap_types:
        hints.append("Add an explicit smoke check for the external program or service before promotion.")
    if not hints:
        hints.append("Inspect existing local tools and install only the smallest missing dependency slice.")
    return _unique(hints)


def _validation_hints(requirements: TaskRequirementGraph) -> list[str]:
    hints = [
        *_normalized_list(requirements.replay_contract.get("validation_hints", [])),
        *_normalized_list(requirements.implementation_contract.get("validation_steps", [])),
        "Verify the new plugin, command, skill, agent, and MCP surfaces are discoverable.",
        "Replay the original blocked task in a fresh session instead of only checking file existence.",
    ]
    if requirements.operation_specs:
        operation_names = ", ".join(item["name"] for item in requirements.operation_specs[:5])
        hints.append(f"Exercise the key workflow operations during replay: {operation_names}.")
    if requirements.deliverables:
        hints.append("Confirm the requested deliverables are produced with the expected structure and location.")
    if requirements.state_targets:
        state_names = ", ".join(requirements.state_targets[:5])
        hints.append(f"Confirm reusable state survives replay and stays bounded: {state_names}.")
    if {"api-service", "remote-service", "cli-runtime", "local-command", "network-access", "container-runtime", "kubernetes-cluster"} & set(
        requirements.external_dependencies
    ):
        hints.append("Run one explicit dependency smoke check so replay proves the external capability is actually reachable.")
    if requirements.reuse_across_sessions:
        hints.append("Confirm the replay succeeds without rediscovering the setup from scratch.")
    return _unique(hints)


def _workflow_outline(requirements: TaskRequirementGraph) -> list[str]:
    contract_outline = _normalized_list(requirements.implementation_contract.get("concrete_operations", []))
    if contract_outline:
        return contract_outline
    outline = [item["summary"] for item in requirements.operation_specs]
    return outline or ["Inspect the current capability surface and implement the minimum replayable slice."]


def _mcp_tool_specs(requirements: TaskRequirementGraph) -> list[dict[str, str]]:
    if _is_browser_like(requirements):
        return [
            {"name": "inspect_capability_status", "description": "Inspect whether browser automation is fully implemented."},
            {"name": "run_browser_flow", "description": "Run a browser flow with navigation, optional interaction steps, screenshot capture, and persistent session state."},
            {"name": "list_saved_browser_sessions", "description": "List saved browser session state files for reuse."},
        ]
    return [
        {"name": "inspect_capability_status", "description": "Inspect workspace support, saved state, operations, and dependency hints for the synthesized capability."},
        {"name": "run_capability_workflow", "description": "Execute a declarative workflow plan across shell, file, HTTP, and state operations."},
        {"name": "read_capability_artifact", "description": "Read an input or output artifact from the workspace for the synthesized capability."},
        {"name": "write_capability_output", "description": "Write the requested output artifact or structured payload."},
        {"name": "save_reusable_state", "description": "Persist reusable capability state for future sessions."},
        {"name": "load_reusable_state", "description": "Restore previously saved reusable capability state."},
        {"name": "list_reusable_state", "description": "List saved reusable state entries for this capability."},
        {"name": "validate_capability_contract", "description": "Summarize the capability contract, required operations, and validation expectations."},
    ]


def _requirements_file_content(requirements: TaskRequirementGraph) -> str:
    lines: list[str] = []
    contract_dependencies = _normalized_list(requirements.implementation_contract.get("runtime_dependencies", []))
    if _is_browser_like(requirements):
        lines.append("playwright>=1.45")
    if _is_document_like(requirements):
        lines.append("python-docx>=1.1")
    if _is_database_like(requirements):
        lines.append("sqlalchemy>=2.0")
    if "api-service" in requirements.external_dependencies:
        lines.append("requests>=2.32")
    if "remote-service" in requirements.external_dependencies and "requests>=2.32" not in lines:
        lines.append("requests>=2.32")
    if "kubernetes-cluster" in requirements.external_dependencies:
        lines.append("# kubernetes>=30.0  # add when cluster automation moves beyond CLI shelling")
    if "container-runtime" in requirements.external_dependencies:
        lines.append("# docker>=7.0  # add if the capability needs direct container engine control")
    if "cli-runtime" in requirements.external_dependencies:
        lines.append("# record CLI bootstrap steps in docs/bootstrap-checklist.md")
    for dependency in contract_dependencies:
        normalized = _normalized_name(dependency)
        if normalized in {"requests", "python-requests"} and "requests>=2.32" not in lines:
            lines.append("requests>=2.32")
        elif normalized in {"python-docx", "docx"} and "python-docx>=1.1" not in lines:
            lines.append("python-docx>=1.1")
        elif normalized == "playwright" and "playwright>=1.45" not in lines:
            lines.append("playwright>=1.45")
        elif normalized in {"kubectl", "ffmpeg"}:
            lines.append(f"# requires `{dependency}` available on PATH")
    return "\n".join(lines).strip() + ("\n" if lines else "")


def _server_script_content(requirements: TaskRequirementGraph, plan: CapabilityGrowthPlan) -> str:
    if _is_browser_like(requirements):
        return _browser_server_script_content(requirements, plan)
    return _generic_server_script_content(requirements, plan)


def _implementation_script_target_paths(
    requirements: TaskRequirementGraph,
    plan: CapabilityGrowthPlan,
    implementation_contract: dict[str, Any],
) -> list[str]:
    surface_kind = _implementation_surface_kind(implementation_contract)
    if surface_kind not in {"executable", "mixed"}:
        return []
    plugin_root = f"plugins/{plan.capability_slug}"
    candidates: list[str] = []
    for raw_path in _normalized_list(implementation_contract.get("deliverable_paths", [])):
        if not raw_path.lower().endswith(".py"):
            continue
        normalized = raw_path.replace("\\", "/").strip("/")
        if normalized.startswith("plugins/"):
            candidates.append(normalized)
            continue
        if "/" in normalized:
            candidates.append(f"{plugin_root}/{normalized}")
            continue
        candidates.append(f"{plugin_root}/scripts/{normalized}")
    if candidates:
        return _unique(candidates)
    if _is_kubernetes_like(requirements):
        return [f"{plugin_root}/scripts/{plan.capability_slug.replace('-', '_')}.py"]
    return []


def _implementation_script_content(
    requirements: TaskRequirementGraph,
    plan: CapabilityGrowthPlan,
    implementation_contract: dict[str, Any],
    *,
    target_path: str,
) -> str:
    if _is_kubernetes_like(requirements):
        return _kubernetes_execution_script_content(
            requirements,
            plan,
            implementation_contract,
            target_path=target_path,
        )
    return _generic_execution_script_content(
        requirements,
        plan,
        implementation_contract,
        target_path=target_path,
    )


def _surface_group_mentions_capability(
    surface: CapabilitySurfaceGraph,
    surface_name: str,
    keywords: list[str],
) -> bool:
    items = _surface_items_for_name(surface, surface_name)
    if not items:
        return False
    keyword_tokens = {token for keyword in keywords for token in _surface_item_tokens(keyword)}
    if not keyword_tokens:
        return False
    for item in items:
        item_tokens = _surface_item_tokens(item)
        if not item_tokens:
            continue
        if item in keywords:
            return True
        overlap = item_tokens & keyword_tokens
        if len(overlap) >= 2:
            return True
        if len(item_tokens) == 1 and overlap:
            return True
    return False


def _capability_keywords(requirements: TaskRequirementGraph, capability_slug: str) -> list[str]:
    keywords = [capability_slug, requirements.capability_name.lower()]
    keywords.extend(requirements.input_objects)
    keywords.extend(requirements.input_formats)
    keywords.extend(requirements.environment_targets)
    keywords.extend(requirements.domain_tags)
    keywords.extend(requirements.deliverables)
    keywords.extend(requirements.workflow_actions)
    keywords.extend(item["name"] for item in requirements.operation_specs)
    keywords.extend(requirements.state_targets)
    if "browser" in requirements.environment_targets:
        keywords.extend(["browser", "playwright", "selenium", "puppeteer", "screenshot"])
    if "document" in requirements.environment_targets:
        keywords.extend(["document", "docx", "word", "report"])
    if "kubernetes" in requirements.environment_targets:
        keywords.extend(["kubernetes", "k8s", "kubectl", "cluster"])
    if "api" in requirements.environment_targets:
        keywords.extend(["api", "endpoint", "http", "request"])
    return _unique([_normalized_name(keyword) for keyword in keywords if keyword])


def _dependency_keywords(requirements: TaskRequirementGraph) -> list[str]:
    keywords: list[str] = []
    for dependency in requirements.external_dependencies:
        if dependency == "filesystem-access":
            continue
        keywords.extend(_meaningful_tokens(dependency))
    return _unique(keywords)


def _requires_mcp_surface(requirements: TaskRequirementGraph) -> bool:
    if "mcp" in requirements.requested_surfaces:
        return True
    return any(
        item not in {"filesystem-access"}
        for item in requirements.external_dependencies
    )


def _surface_items_for_name(surface: CapabilitySurfaceGraph, surface_name: str) -> list[str]:
    if surface_name == "plugin":
        return list(surface.plugins)
    if surface_name == "skill":
        return list(surface.skills)
    if surface_name == "command":
        return list(surface.commands)
    if surface_name == "agent":
        return list(surface.agents)
    if surface_name == "mcp":
        return list(surface.mcp_servers)
    return []


def _surface_item_tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value.lower()) if token}


def _unique_operation_specs(items: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        name = _normalized_name(str(item.get("name", "")))
        if not name or name in seen:
            continue
        seen.add(name)
        result.append({"name": name, "summary": str(item.get("summary", "")).strip() or name})
    return result


def _meaningful_tokens(text: str) -> list[str]:
    return [
        token
        for token in re.split(r"[^a-z0-9]+", str(text).lower())
        if token and token not in _COMMON_FILLER_TOKENS and not token.isdigit()
    ]


def _normalize_dependency_labels(items: list[str], *, text: str) -> list[str]:
    labels = [_normalized_name(item) for item in items if _normalized_name(item)]
    if "filesystem-access" not in labels:
        labels.insert(0, "filesystem-access")
    return _unique(labels)


def _quoted_spans(text: str) -> list[str]:
    return [match.group(1).strip() for match in re.finditer(r"[\"']([^\"']{3,80})[\"']", text) if match.group(1).strip()]


def _collect_following_phrases(text: str, anchors: tuple[str, ...]) -> list[str]:
    phrases: list[str] = []
    for anchor in anchors:
        pattern = re.compile(rf"\b{re.escape(anchor)}\b(?:\s+(?:of|for|to|named))?\s+([A-Za-z0-9_./:-]{{3,80}})", re.IGNORECASE)
        for match in pattern.finditer(text):
            phrases.append(match.group(1).strip())
    return phrases


def _is_browser_like(requirements: TaskRequirementGraph) -> bool:
    corpus = "\n".join(
        [
            requirements.capability_name,
            *requirements.input_objects,
            *requirements.deliverables,
            *requirements.workflow_actions,
            *requirements.external_dependencies,
            *requirements.domain_tags,
        ]
    ).lower()
    return any(token in corpus for token in ("browser", "website", "page", "url", "screenshot", "playwright", "selenium", "puppeteer"))


def _is_document_like(requirements: TaskRequirementGraph) -> bool:
    corpus = "\n".join(
        [
            requirements.capability_name,
            *requirements.input_objects,
            *requirements.deliverables,
            *requirements.external_dependencies,
            *requirements.domain_tags,
        ]
    ).lower()
    return any(token in corpus for token in ("document", "docx", "word", "pdf"))


def _is_database_like(requirements: TaskRequirementGraph) -> bool:
    corpus = "\n".join(
        [
            requirements.capability_name,
            *requirements.input_objects,
            *requirements.workflow_actions,
            *requirements.external_dependencies,
            *requirements.domain_tags,
        ]
    ).lower()
    return any(token in corpus for token in ("database", "sql", "table", "query", "postgres", "mysql", "sqlite", "mongo", "redis"))


def _is_kubernetes_like(requirements: TaskRequirementGraph) -> bool:
    corpus = "\n".join(
        [
            requirements.capability_name,
            *requirements.input_objects,
            *requirements.workflow_actions,
            *requirements.external_dependencies,
            *requirements.domain_tags,
            *requirements.deliverables,
        ]
    ).lower()
    return any(token in corpus for token in ("kubernetes", "k8s", "kubectl", "pod", "namespace", "cluster"))


def _workspace_markdown_asset_names(workspace_root: Path, asset_dir: str) -> list[str]:
    patterns = [
        f".claude/{asset_dir}/*.md",
        f".openharness/{asset_dir}/*.md",
        f"{asset_dir}/*.md",
        f"plugins/*/{asset_dir}/*.md",
    ]
    names: list[str] = []
    for pattern in patterns:
        for path in workspace_root.glob(pattern):
            frontmatter_name = _frontmatter_name(path)
            names.append(frontmatter_name or path.stem)
    return sorted(set(name for name in names if name))


def _plugin_names_from_fs(workspace_root: Path) -> list[str]:
    names: list[str] = []
    plugin_root = workspace_root / "plugins"
    if not plugin_root.exists():
        return []
    for plugin_dir in plugin_root.iterdir():
        if not plugin_dir.is_dir():
            continue
        manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
        if not manifest_path.exists():
            continue
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        names.append(str(payload.get("name", plugin_dir.name)).strip())
    return sorted(set(name for name in names if name))


def _mcp_server_names_from_fs(workspace_root: Path) -> list[str]:
    server_names: list[str] = []
    for path in (
        workspace_root / ".mcp.json",
        workspace_root / ".evo-harness" / "mcp.json",
        workspace_root / ".openharness" / "mcp.json",
    ):
        server_names.extend(_server_names_from_mcp_file(path))

    plugin_root = workspace_root / "plugins"
    if plugin_root.exists():
        for plugin_dir in plugin_root.iterdir():
            if not plugin_dir.is_dir():
                continue
            manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
            mcp_path = plugin_dir / ".mcp.json"
            if not manifest_path.exists() or not mcp_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            plugin_name = str(manifest.get("name", plugin_dir.name)).strip()
            for server_name in _server_names_from_mcp_file(mcp_path):
                if plugin_name:
                    server_names.append(f"{plugin_name}:{server_name}")
                else:
                    server_names.append(server_name)
    return sorted(set(name for name in server_names if name))


def _frontmatter_name(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if not text.startswith("---\n"):
        return ""
    lines = text.splitlines()
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.lower().startswith("name:"):
            return line.split(":", 1)[1].strip()
    return ""


def _server_names_from_mcp_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    servers = payload.get("mcpServers", {})
    if not isinstance(servers, dict):
        return []
    return [str(name).strip() for name in servers if str(name).strip()]


def _dependency_markers(workspace_root: Path) -> list[str]:
    candidates = [
        workspace_root / "pyproject.toml",
        workspace_root / "package.json",
        workspace_root / "requirements.txt",
        workspace_root / "requirements-dev.txt",
    ]
    markers: list[str] = []
    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        markers.extend(_dependency_names_from_file(path.name.lower(), text))
    return _unique(markers)


def _dependency_names_from_file(filename: str, text: str) -> list[str]:
    if filename == "package.json":
        return _package_json_dependency_names(text)
    if filename.endswith(".toml"):
        return _toml_dependency_names(text)
    return _requirements_dependency_names(text)


def _requirements_dependency_names(text: str) -> list[str]:
    names: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        line = re.split(r"[<>=!~\[]", line, 1)[0].strip()
        if line:
            names.append(_normalized_name(line))
    return _unique(names)


def _toml_dependency_names(text: str) -> list[str]:
    names: list[str] = []
    for match in re.finditer(r'["\']([A-Za-z0-9_.-]+)(?:\[[A-Za-z0-9_,.-]+\])?(?:[<>=!~].*?)?["\']', text):
        token = str(match.group(1)).strip()
        if token and not token.lower().startswith("python"):
            names.append(_normalized_name(token))
    for match in re.finditer(r"^\s*([A-Za-z0-9_.-]+)\s*=\s*['\"]", text, flags=re.MULTILINE):
        token = str(match.group(1)).strip()
        if token and token.lower() not in {"project", "tool", "python"}:
            names.append(_normalized_name(token))
    return _unique(names)


def _package_json_dependency_names(text: str) -> list[str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    names: list[str] = []
    for section in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        values = payload.get(section, {})
        if isinstance(values, dict):
            names.extend(_normalized_name(str(key)) for key in values if str(key).strip())
    return _unique(names)


def _normalized_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _unique(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = str(item).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _generic_server_script_content(requirements: TaskRequirementGraph, plan: CapabilityGrowthPlan) -> str:
    capability_name = json.dumps(requirements.capability_name)
    capability_slug = json.dumps(plan.capability_slug)
    operation_specs = json.dumps(requirements.operation_specs, ensure_ascii=False)
    deliverables = json.dumps(requirements.deliverables, ensure_ascii=False)
    state_targets = json.dumps(requirements.state_targets, ensure_ascii=False)
    validation_hints = json.dumps(plan.validation_hints, ensure_ascii=False)
    implementation_contract = json.dumps(requirements.implementation_contract, ensure_ascii=False)
    replay_contract = json.dumps(requirements.replay_contract, ensure_ascii=False)
    return "\n".join(
        [
            "from __future__ import annotations",
            "",
            "import json",
            "import os",
            "import subprocess",
            "import sys",
            "import urllib.request",
            "from pathlib import Path",
            "",
            "",
            "PROTOCOL_VERSION = '2025-06-18'",
            f"CAPABILITY_NAME = {capability_name}",
            f"CAPABILITY_SLUG = {capability_slug}",
            f"OPERATION_SPECS = {operation_specs}",
            f"DELIVERABLES = {deliverables}",
            f"STATE_TARGETS = {state_targets}",
            f"VALIDATION_HINTS = {validation_hints}",
            f"IMPLEMENTATION_CONTRACT = {implementation_contract}",
            f"REPLAY_CONTRACT = {replay_contract}",
            "",
            "",
            "def _workspace_root() -> Path:",
            "    configured = os.environ.get('EVO_HARNESS_WORKSPACE', '').strip()",
            "    if configured:",
            "        return Path(configured).resolve()",
            "    return Path.cwd().resolve()",
            "",
            "",
            "def _runtime_dir() -> Path:",
            "    path = Path(__file__).resolve().parent / '.runtime'",
            "    path.mkdir(parents=True, exist_ok=True)",
            "    return path",
            "",
            "",
            "def _inspect_capability_status() -> dict[str, object]:",
            "    return {",
            "        'capability': CAPABILITY_NAME,",
            "        'workspace': str(_workspace_root()),",
            "        'runtime_dir': str(_runtime_dir()),",
            "        'status': 'workflow-ready-template',",
            "        'operations': OPERATION_SPECS,",
            "        'deliverables': DELIVERABLES,",
            "        'state_targets': STATE_TARGETS,",
            "        'validation_hints': VALIDATION_HINTS,",
            "        'implementation_contract': IMPLEMENTATION_CONTRACT,",
            "        'replay_contract': REPLAY_CONTRACT,",
            "        'notes': [",
            "            'This is a generic capability workflow server.',",
            "            'Use run_capability_workflow with explicit step kinds such as run_command, http_get, read_file, write_output, save_state, and load_state.',",
            "        ],",
            "    }",
            "",
            "",
            "def _resolve_workspace_path(path_text: str) -> Path:",
            "    raw = Path(path_text)",
            "    if raw.is_absolute():",
            "        return raw.resolve()",
            "    return (_workspace_root() / raw).resolve()",
            "",
            "",
            "def _read_capability_artifact(arguments: dict[str, object]) -> dict[str, object]:",
            "    path_text = str(arguments.get('path', '')).strip()",
            "    if not path_text:",
            "        raise ValueError('`path` is required.')",
            "    target = _resolve_workspace_path(path_text)",
            "    if not target.exists():",
            "        raise FileNotFoundError(f'Artifact not found: {target}')",
            "    text = target.read_text(encoding='utf-8', errors='replace')",
            "    max_chars = int(arguments.get('max_chars', 12000) or 12000)",
            "    return {'path': str(target), 'text': text[:max_chars], 'bytes': target.stat().st_size}",
            "",
            "",
            "def _http_get(step: dict[str, object]) -> dict[str, object]:",
            "    url = str(step.get('url', '')).strip()",
            "    if not url:",
            "        raise ValueError('http_get step requires `url`.')",
            "    request = urllib.request.Request(url, headers={'User-Agent': 'EvoHarnessCapability/0.1'})",
            "    with urllib.request.urlopen(request, timeout=int(step.get('timeout_sec', 20) or 20)) as response:",
            "        body = response.read().decode('utf-8', errors='replace')",
            "    return {'kind': 'http_get', 'url': url, 'status_code': getattr(response, 'status', None), 'text': body[: int(step.get('max_chars', 4000) or 4000)]}",
            "",
            "",
            "def _run_command(step: dict[str, object]) -> dict[str, object]:",
            "    argv = step.get('argv')",
            "    if not isinstance(argv, list) or not argv:",
            "        raise ValueError('run_command step requires non-empty `argv` list.')",
            "    cwd_text = str(step.get('cwd', '')).strip()",
            "    cwd = _resolve_workspace_path(cwd_text) if cwd_text else _workspace_root()",
            "    completed = subprocess.run(",
            "        [str(item) for item in argv],",
            "        cwd=str(cwd),",
            "        capture_output=True,",
            "        text=True,",
            "        encoding='utf-8',",
            "        errors='replace',",
            "        timeout=int(step.get('timeout_sec', 60) or 60),",
            "        check=False,",
            "    )",
            "    return {",
            "        'kind': 'run_command',",
            "        'argv': [str(item) for item in argv],",
            "        'cwd': str(cwd),",
            "        'returncode': completed.returncode,",
            "        'stdout': completed.stdout[:8000],",
            "        'stderr': completed.stderr[:8000],",
            "    }",
            "",
            "",
            "def _run_capability_workflow(arguments: dict[str, object]) -> dict[str, object]:",
            "    steps = list(arguments.get('steps', []) or [])",
            "    results = []",
            "    for raw_step in steps:",
            "        step = dict(raw_step or {})",
            "        kind = str(step.get('kind', '')).strip()",
            "        if kind == 'run_command':",
            "            results.append(_run_command(step))",
            "        elif kind == 'http_get':",
            "            results.append(_http_get(step))",
            "        elif kind == 'read_file':",
            "            results.append(_read_capability_artifact(step))",
            "        elif kind == 'write_output':",
            "            results.append(_write_capability_output(step))",
            "        elif kind == 'save_state':",
            "            results.append(_save_reusable_state(step))",
            "        elif kind == 'load_state':",
            "            results.append(_load_reusable_state(step))",
            "        else:",
            "            raise ValueError(f'Unsupported workflow step kind: {kind}')",
            "    return {'capability': CAPABILITY_NAME, 'executed_steps': results, 'step_count': len(results)}",
            "",
            "",
            "def _write_capability_output(arguments: dict[str, object]) -> dict[str, object]:",
            "    path_text = str(arguments.get('path', '')).strip()",
            "    if not path_text:",
            "        raise ValueError('`path` is required.')",
            "    content = str(arguments.get('content', '') or '')",
            "    target = _resolve_workspace_path(path_text)",
            "    target.parent.mkdir(parents=True, exist_ok=True)",
            "    target.write_text(content, encoding='utf-8')",
            "    return {'path': str(target), 'bytes': len(content.encode('utf-8'))}",
            "",
            "",
            "def _save_reusable_state(arguments: dict[str, object]) -> dict[str, object]:",
            "    name = str(arguments.get('name', '')).strip() or CAPABILITY_SLUG",
            "    payload = dict(arguments.get('payload', {}) or {})",
            "    path = _runtime_dir() / f'{name}.json'",
            "    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')",
            "    return {'path': str(path), 'keys': sorted(payload.keys())}",
            "",
            "",
            "def _load_reusable_state(arguments: dict[str, object]) -> dict[str, object]:",
            "    name = str(arguments.get('name', '')).strip() or CAPABILITY_SLUG",
            "    path = _runtime_dir() / f'{name}.json'",
            "    if not path.exists():",
            "        raise FileNotFoundError(f'State file not found: {path}')",
            "    return {'path': str(path), 'payload': json.loads(path.read_text(encoding='utf-8'))}",
            "",
            "",
            "def _list_reusable_state(arguments: dict[str, object]) -> dict[str, object]:",
            "    files = []",
            "    for path in sorted(_runtime_dir().glob('*.json')):",
            "        files.append({'name': path.stem, 'path': str(path), 'bytes': path.stat().st_size})",
            "    return {'state_files': files}",
            "",
            "",
            "def _validate_capability_contract(arguments: dict[str, object]) -> dict[str, object]:",
            "    return {",
            "        'capability': CAPABILITY_NAME,",
            "        'operations': OPERATION_SPECS,",
            "        'deliverables': DELIVERABLES,",
            "        'state_targets': STATE_TARGETS,",
            "        'validation_hints': VALIDATION_HINTS,",
            "    }",
            "",
            "",
            "def _handle_method(method: str, params: dict[str, object]) -> dict[str, object]:",
            "    if method == 'initialize':",
            "        return {",
            "            'protocolVersion': PROTOCOL_VERSION,",
            "            'serverInfo': {'name': CAPABILITY_SLUG, 'version': '0.1.0'},",
            "            'capabilities': {'tools': {}, 'resources': {}, 'prompts': {}},",
            "        }",
            "    if method == 'tools/list':",
            "        return {",
            "            'tools': [",
            "                {'name': 'inspect_capability_status', 'description': 'Inspect the synthesized capability status.', 'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}},",
            "                {'name': 'run_capability_workflow', 'description': 'Execute a declarative capability workflow.', 'inputSchema': {'type': 'object', 'properties': {'steps': {'type': 'array', 'items': {'type': 'object'}}}, 'additionalProperties': True}},",
            "                {'name': 'read_capability_artifact', 'description': 'Read an input or output artifact from the workspace.', 'inputSchema': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'max_chars': {'type': 'integer'}}, 'required': ['path'], 'additionalProperties': False}},",
            "                {'name': 'write_capability_output', 'description': 'Write an output artifact to the workspace.', 'inputSchema': {'type': 'object', 'properties': {'path': {'type': 'string'}, 'content': {'type': 'string'}}, 'required': ['path'], 'additionalProperties': False}},",
            "                {'name': 'save_reusable_state', 'description': 'Persist reusable capability state.', 'inputSchema': {'type': 'object', 'properties': {'name': {'type': 'string'}, 'payload': {'type': 'object'}}, 'additionalProperties': True}},",
            "                {'name': 'load_reusable_state', 'description': 'Load previously saved reusable state.', 'inputSchema': {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'additionalProperties': False}},",
            "                {'name': 'list_reusable_state', 'description': 'List reusable capability state files.', 'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}},",
            "                {'name': 'validate_capability_contract', 'description': 'Return the capability contract and validation hints.', 'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}},",
            "            ]",
            "        }",
            "    if method == 'tools/call':",
            "        name = str(params.get('name', ''))",
            "        arguments = dict(params.get('arguments', {}) or {})",
            "        if name == 'inspect_capability_status':",
            "            payload = _inspect_capability_status()",
            "        elif name == 'run_capability_workflow':",
            "            payload = _run_capability_workflow(arguments)",
            "        elif name == 'read_capability_artifact':",
            "            payload = _read_capability_artifact(arguments)",
            "        elif name == 'write_capability_output':",
            "            payload = _write_capability_output(arguments)",
            "        elif name == 'save_reusable_state':",
            "            payload = _save_reusable_state(arguments)",
            "        elif name == 'load_reusable_state':",
            "            payload = _load_reusable_state(arguments)",
            "        elif name == 'list_reusable_state':",
            "            payload = _list_reusable_state(arguments)",
            "        elif name == 'validate_capability_contract':",
            "            payload = _validate_capability_contract(arguments)",
            "        else:",
            "            raise ValueError(f'Unknown tool: {name}')",
            "        return {'content': [{'type': 'text', 'text': json.dumps(payload, indent=2, ensure_ascii=False)}]}",
            "    if method == 'resources/list':",
            "        return {'resources': []}",
            "    if method == 'prompts/list':",
            "        return {'prompts': []}",
            "    if method == 'notifications/initialized':",
            "        return {}",
            "    raise ValueError(f'Unsupported MCP method: {method}')",
            "",
            "",
            "def _read_message() -> dict[str, object] | None:",
            "    headers: dict[str, str] = {}",
            "    while True:",
            "        line = sys.stdin.buffer.readline()",
            "        if not line:",
            "            return None",
            "        if line == b'\\r\\n':",
            "            break",
            "        key, value = line.decode('ascii').split(':', 1)",
            "        headers[key.strip().lower()] = value.strip()",
            "    length = int(headers.get('content-length', '0'))",
            "    body = sys.stdin.buffer.read(length)",
            "    return json.loads(body.decode('utf-8'))",
            "",
            "",
            "def _write_message(payload: dict[str, object]) -> None:",
            "    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')",
            "    header = f'Content-Length: {len(body)}\\r\\n\\r\\n'.encode('ascii')",
            "    sys.stdout.buffer.write(header + body)",
            "    sys.stdout.buffer.flush()",
            "",
            "",
            "def main() -> None:",
            "    while True:",
            "        message = _read_message()",
            "        if message is None:",
            "            return",
            "        method = str(message.get('method', ''))",
            "        request_id = message.get('id')",
            "        try:",
            "            result = _handle_method(method, dict(message.get('params', {}) or {}))",
            "            if request_id is not None:",
            "                _write_message({'jsonrpc': '2.0', 'id': request_id, 'result': result})",
            "        except Exception as exc:",
            "            if request_id is not None:",
            "                _write_message({'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32000, 'message': str(exc)}})",
            "",
            "",
            "if __name__ == '__main__':",
            "    main()",
            "",
        ]
    )


def _browser_server_script_content(requirements: TaskRequirementGraph, plan: CapabilityGrowthPlan) -> str:
    capability_name = json.dumps(requirements.capability_name)
    capability_slug = json.dumps(plan.capability_slug)
    return "\n".join(
        [
            "from __future__ import annotations",
            "",
            "import json",
            "import os",
            "import sys",
            "from pathlib import Path",
            "from typing import Any",
            "",
            "",
            "PROTOCOL_VERSION = '2025-06-18'",
            f"CAPABILITY_NAME = {capability_name}",
            f"CAPABILITY_SLUG = {capability_slug}",
            "",
            "",
            "def _workspace_root() -> Path:",
            "    configured = os.environ.get('EVO_HARNESS_WORKSPACE', '').strip()",
            "    if configured:",
            "        return Path(configured).resolve()",
            "    return Path.cwd().resolve()",
            "",
            "",
            "def _runtime_dir() -> Path:",
            "    path = Path(__file__).resolve().parent / '.runtime'",
            "    path.mkdir(parents=True, exist_ok=True)",
            "    return path",
            "",
            "",
            "def _saved_session_path(session_name: str) -> Path:",
            "    safe = ''.join(ch if ch.isalnum() or ch in ('-', '_') else '-' for ch in session_name).strip('-') or 'default'",
            "    return _runtime_dir() / f'{safe}.json'",
            "",
            "",
            "def _resolve_workspace_path(path_text: str) -> Path:",
            "    raw = Path(path_text)",
            "    if raw.is_absolute():",
            "        return raw",
            "    return (_workspace_root() / raw).resolve()",
            "",
            "",
            "def _playwright_status() -> tuple[bool, str]:",
            "    try:",
            "        from playwright.sync_api import sync_playwright  # noqa: F401",
            "        return True, ''",
            "    except Exception as exc:",
            "        return False, str(exc)",
            "",
            "",
            "def _inspect_capability_status() -> dict[str, Any]:",
            "    installed, error = _playwright_status()",
            "    saved_sessions = sorted(path.name for path in _runtime_dir().glob('*.json'))",
            "    return {",
            "        'capability': CAPABILITY_NAME,",
            "        'workspace': str(_workspace_root()),",
            "        'playwright_installed': installed,",
            "        'playwright_error': error,",
            "        'saved_sessions': saved_sessions,",
            "        'notes': [",
            "            'Install dependencies from requirements.txt and run `python -m playwright install chromium` before promotion.',",
            "            'Use run_browser_flow with steps to navigate, authenticate, capture screenshots, and persist session state.',",
            "        ],",
            "    }",
            "",
            "",
            "def _list_saved_browser_sessions() -> dict[str, Any]:",
            "    sessions = []",
            "    for path in sorted(_runtime_dir().glob('*.json')):",
            "        sessions.append({'name': path.stem, 'path': str(path), 'bytes': path.stat().st_size})",
            "    return {'sessions': sessions}",
            "",
            "",
            "def _apply_step(page, step: dict[str, Any]) -> dict[str, Any]:",
            "    kind = str(step.get('kind', '')).strip().lower()",
            "    if kind == 'goto':",
            "        url = str(step.get('url', '')).strip()",
            "        if not url:",
            "            raise ValueError('goto step requires `url`.')",
            "        page.goto(url, wait_until=str(step.get('wait_until', 'networkidle')))",
            "        return {'kind': kind, 'url': url}",
            "    if kind == 'click':",
            "        selector = str(step.get('selector', '')).strip()",
            "        page.locator(selector).click(timeout=int(step.get('timeout_ms', 15000)))",
            "        return {'kind': kind, 'selector': selector}",
            "    if kind == 'fill':",
            "        selector = str(step.get('selector', '')).strip()",
            "        value = str(step.get('value', '') or '')",
            "        page.locator(selector).fill(value, timeout=int(step.get('timeout_ms', 15000)))",
            "        return {'kind': kind, 'selector': selector}",
            "    if kind == 'press':",
            "        selector = str(step.get('selector', '')).strip()",
            "        key = str(step.get('key', '')).strip()",
            "        page.locator(selector).press(key, timeout=int(step.get('timeout_ms', 15000)))",
            "        return {'kind': kind, 'selector': selector, 'key': key}",
            "    if kind == 'wait_for':",
            "        selector = str(step.get('selector', '')).strip()",
            "        state = str(step.get('state', 'visible')).strip()",
            "        page.locator(selector).wait_for(state=state, timeout=int(step.get('timeout_ms', 15000)))",
            "        return {'kind': kind, 'selector': selector, 'state': state}",
            "    if kind == 'screenshot':",
            "        return {'kind': kind, 'deferred': True}",
            "    raise ValueError(f'Unsupported browser step kind: {kind}')",
            "",
            "",
            "def _run_browser_flow(arguments: dict[str, Any]) -> dict[str, Any]:",
            "    installed, error = _playwright_status()",
            "    if not installed:",
            "        raise RuntimeError(",
            "            'Playwright is not installed or not importable. '",
            "            'Install requirements.txt and run `python -m playwright install chromium`. '",
            "            f'Import error: {error}'",
            "        )",
            "    url = str(arguments.get('url', '')).strip()",
            "    session_name = str(arguments.get('session_name', '')).strip() or CAPABILITY_SLUG",
            "    screenshot_path_text = str(arguments.get('screenshot_path', '')).strip()",
            "    screenshot_path = _resolve_workspace_path(screenshot_path_text) if screenshot_path_text else (_workspace_root() / f'{session_name}.png').resolve()",
            "    screenshot_path.parent.mkdir(parents=True, exist_ok=True)",
            "    session_state_path = _saved_session_path(session_name)",
            "    steps = list(arguments.get('steps', []) or [])",
            "    headless = bool(arguments.get('headless', True))",
            "    full_page = bool(arguments.get('full_page', True))",
            "    save_session_state = bool(arguments.get('save_session_state', True))",
            "",
            "    from playwright.sync_api import sync_playwright",
            "",
            "    executed_steps = []",
            "    with sync_playwright() as playwright:",
            "        browser = playwright.chromium.launch(headless=headless)",
            "        context_kwargs: dict[str, Any] = {}",
            "        if session_state_path.exists():",
            "            context_kwargs['storage_state'] = str(session_state_path)",
            "        context = browser.new_context(**context_kwargs)",
            "        page = context.new_page()",
            "        if url:",
            "            page.goto(url, wait_until=str(arguments.get('wait_until', 'networkidle')))",
            "            executed_steps.append({'kind': 'goto', 'url': url})",
            "        for step in steps:",
            "            executed_steps.append(_apply_step(page, dict(step)))",
            "        page.screenshot(path=str(screenshot_path), full_page=full_page)",
            "        if save_session_state:",
            "            context.storage_state(path=str(session_state_path))",
            "        title = page.title()",
            "        current_url = page.url",
            "        context.close()",
            "        browser.close()",
            "",
            "    return {",
            "        'capability': CAPABILITY_NAME,",
            "        'session_name': session_name,",
            "        'url': current_url,",
            "        'title': title,",
            "        'screenshot_path': str(screenshot_path),",
            "        'session_state_path': str(session_state_path) if save_session_state else '',",
            "        'executed_steps': executed_steps,",
            "        'headless': headless,",
            "    }",
            "",
            "",
            "def _handle_method(method: str, params: dict[str, Any]) -> dict[str, Any]:",
            "    if method == 'initialize':",
            "        return {",
            "            'protocolVersion': PROTOCOL_VERSION,",
            "            'serverInfo': {'name': CAPABILITY_SLUG, 'version': '0.1.0'},",
            "            'capabilities': {'tools': {}, 'resources': {}, 'prompts': {}},",
            "        }",
            "    if method == 'tools/list':",
            "        return {",
            "            'tools': [",
            "                {'name': 'inspect_capability_status', 'description': 'Inspect browser automation dependency and session status.', 'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}},",
            "                {'name': 'run_browser_flow', 'description': 'Run a browser flow with navigation, optional interaction steps, screenshot capture, and session persistence.', 'inputSchema': {'type': 'object', 'properties': {'url': {'type': 'string'}, 'session_name': {'type': 'string'}, 'screenshot_path': {'type': 'string'}, 'headless': {'type': 'boolean'}, 'full_page': {'type': 'boolean'}, 'save_session_state': {'type': 'boolean'}, 'steps': {'type': 'array', 'items': {'type': 'object'}}}, 'additionalProperties': True}},",
            "                {'name': 'list_saved_browser_sessions', 'description': 'List saved browser session state files.', 'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}},",
            "            ]",
            "        }",
            "    if method == 'tools/call':",
            "        name = str(params.get('name', ''))",
            "        arguments = dict(params.get('arguments', {}) or {})",
            "        if name == 'inspect_capability_status':",
            "            payload = _inspect_capability_status()",
            "        elif name == 'run_browser_flow':",
            "            payload = _run_browser_flow(arguments)",
            "        elif name == 'list_saved_browser_sessions':",
            "            payload = _list_saved_browser_sessions()",
            "        else:",
            "            raise ValueError(f'Unknown tool: {name}')",
            "        return {'content': [{'type': 'text', 'text': json.dumps(payload, indent=2, ensure_ascii=False)}]}",
            "    if method == 'resources/list':",
            "        return {'resources': []}",
            "    if method == 'prompts/list':",
            "        return {'prompts': []}",
            "    if method == 'notifications/initialized':",
            "        return {}",
            "    raise ValueError(f'Unsupported MCP method: {method}')",
            "",
            "",
            "def _read_message() -> dict[str, Any] | None:",
            "    headers: dict[str, str] = {}",
            "    while True:",
            "        line = sys.stdin.buffer.readline()",
            "        if not line:",
            "            return None",
            "        if line == b'\\r\\n':",
            "            break",
            "        key, value = line.decode('ascii').split(':', 1)",
            "        headers[key.strip().lower()] = value.strip()",
            "    length = int(headers.get('content-length', '0'))",
            "    body = sys.stdin.buffer.read(length)",
            "    return json.loads(body.decode('utf-8'))",
            "",
            "",
            "def _write_message(payload: dict[str, Any]) -> None:",
            "    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')",
            "    header = f'Content-Length: {len(body)}\\r\\n\\r\\n'.encode('ascii')",
            "    sys.stdout.buffer.write(header + body)",
            "    sys.stdout.buffer.flush()",
            "",
            "",
            "def main() -> None:",
            "    while True:",
            "        message = _read_message()",
            "        if message is None:",
            "            return",
            "        method = str(message.get('method', ''))",
            "        request_id = message.get('id')",
            "        try:",
            "            result = _handle_method(method, dict(message.get('params', {}) or {}))",
            "            if request_id is not None:",
            "                _write_message({'jsonrpc': '2.0', 'id': request_id, 'result': result})",
            "        except Exception as exc:",
            "            if request_id is not None:",
            "                _write_message({'jsonrpc': '2.0', 'id': request_id, 'error': {'code': -32000, 'message': str(exc)}})",
            "",
            "",
            "if __name__ == '__main__':",
            "    main()",
            "",
        ]
    )


def _generic_execution_script_content(
    requirements: TaskRequirementGraph,
    plan: CapabilityGrowthPlan,
    implementation_contract: dict[str, Any],
    *,
    target_path: str,
) -> str:
    capability_name = json.dumps(requirements.capability_name)
    implementation_contract_text = json.dumps(implementation_contract, ensure_ascii=False)
    return "\n".join(
        [
            "from __future__ import annotations",
            "",
            "import argparse",
            "import json",
            "from datetime import datetime, timezone",
            "from pathlib import Path",
            "",
            f"CAPABILITY_NAME = {capability_name}",
            f"IMPLEMENTATION_CONTRACT = {implementation_contract_text}",
            f"TARGET_PATH = {json.dumps(target_path)}",
            "",
            "",
            "def build_parser() -> argparse.ArgumentParser:",
            "    parser = argparse.ArgumentParser(description=f'Execute {CAPABILITY_NAME}.')",
            "    parser.add_argument('--output-path', default='', help='Optional report path or output directory.')",
            "    parser.add_argument('--dry-run', action='store_true', help='Print the implementation contract without external side effects.')",
            "    return parser",
            "",
            "",
            "def main() -> int:",
            "    args = build_parser().parse_args()",
            "    payload = {",
            "        'capability': CAPABILITY_NAME,",
            "        'target_path': TARGET_PATH,",
            "        'timestamp': datetime.now(timezone.utc).isoformat(),",
            "        'dry_run': bool(args.dry_run),",
            "        'output_path': args.output_path,",
            "        'implementation_contract': IMPLEMENTATION_CONTRACT,",
            "        'status': 'dry-run' if args.dry_run else 'not-implemented',",
            "    }",
            "    print(json.dumps(payload, ensure_ascii=False, indent=2))",
            "    return 0 if args.dry_run else 1",
            "",
            "",
            "if __name__ == '__main__':",
            "    raise SystemExit(main())",
            "",
        ]
    )


def _kubernetes_execution_script_content(
    requirements: TaskRequirementGraph,
    plan: CapabilityGrowthPlan,
    implementation_contract: dict[str, Any],
    *,
    target_path: str,
) -> str:
    capability_name = json.dumps(requirements.capability_name)
    implementation_contract_text = json.dumps(implementation_contract, ensure_ascii=False)
    return "\n".join(
        [
            "from __future__ import annotations",
            "",
            "import argparse",
            "import json",
            "import subprocess",
            "import sys",
            "from datetime import datetime, timezone",
            "from pathlib import Path",
            "from typing import Any",
            "",
            f"CAPABILITY_NAME = {capability_name}",
            f"IMPLEMENTATION_CONTRACT = {implementation_contract_text}",
            f"TARGET_PATH = {json.dumps(target_path)}",
            "",
            "",
            "def build_parser() -> argparse.ArgumentParser:",
            "    parser = argparse.ArgumentParser(description='Collect Kubernetes incident diagnostics and write reusable reports.')",
            "    parser.add_argument('namespace', nargs='?', default='default', help='Kubernetes namespace to inspect.')",
            "    parser.add_argument('pod_name', nargs='?', default='', help='Pod name to inspect. Optional in --dry-run mode.')",
            "    parser.add_argument('--context', default='', help='Optional kubectl context name.')",
            "    parser.add_argument('--time-window', default='1h', help='Log time window, for example 30m or 1h.')",
            "    parser.add_argument('--output-path', default='incident-report.md', help='Markdown report path or output directory.')",
            "    parser.add_argument('--bundle-path', default='diagnostic-bundle.json', help='Structured JSON bundle output path.')",
            "    parser.add_argument('--container', default='', help='Optional specific container name.')",
            "    parser.add_argument('--include-previous', action='store_true', help='Also collect previous logs for restarted containers.')",
            "    parser.add_argument('--dry-run', action='store_true', help='Print planned kubectl operations without contacting the cluster.')",
            "    return parser",
            "",
            "",
            "def _workspace_root() -> Path:",
            "    configured = Path.cwd()",
            "    return configured.resolve()",
            "",
            "",
            "def _kubectl_prefix(context_name: str) -> list[str]:",
            "    prefix = ['kubectl']",
            "    if context_name.strip():",
            "        prefix.extend(['--context', context_name.strip()])",
            "    return prefix",
            "",
            "",
            "def _run_kubectl(args: list[str], *, timeout_sec: int = 60) -> dict[str, Any]:",
            "    completed = subprocess.run(",
            "        args,",
            "        check=False,",
            "        capture_output=True,",
            "        text=True,",
            "        encoding='utf-8',",
            "        errors='replace',",
            "        timeout=timeout_sec,",
            "    )",
            "    return {",
            "        'argv': args,",
            "        'returncode': completed.returncode,",
            "        'stdout': completed.stdout,",
            "        'stderr': completed.stderr,",
            "    }",
            "",
            "",
            "def _output_paths(output_path_text: str, bundle_path_text: str, namespace: str, pod_name: str) -> tuple[Path, Path]:",
            "    output_path = Path(output_path_text)",
            "    bundle_path = Path(bundle_path_text)",
            "    timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')",
            "    if output_path.suffix.lower() not in {'.md', '.markdown'}:",
            "        output_path = output_path / f'incident-report-{namespace}-{pod_name or \"pod\"}-{timestamp}.md'",
            "    if bundle_path.suffix.lower() != '.json':",
            "        bundle_path = bundle_path / f'diagnostic-bundle-{namespace}-{pod_name or \"pod\"}-{timestamp}.json'",
            "    return output_path.resolve(), bundle_path.resolve()",
            "",
            "",
            "def _planned_operations(args) -> list[list[str]]:",
            "    prefix = _kubectl_prefix(args.context)",
            "    operations = [",
            "        [*prefix, 'get', 'pod', args.pod_name, '-n', args.namespace, '-o', 'json'],",
            "        [*prefix, 'describe', 'pod', args.pod_name, '-n', args.namespace],",
            "        [*prefix, 'get', 'events', '-n', args.namespace, '--field-selector', f'involvedObject.name={args.pod_name}'],",
            "        [*prefix, 'logs', args.pod_name, '-n', args.namespace, '--all-containers=true', f'--since={args.time_window}'],",
            "    ]",
            "    if args.container.strip():",
            "        operations[-1].extend(['-c', args.container.strip()])",
            "    if args.include_previous:",
            "        previous = [*prefix, 'logs', args.pod_name, '-n', args.namespace, '--all-containers=true', '--previous', f'--since={args.time_window}']",
            "        if args.container.strip():",
            "            previous.extend(['-c', args.container.strip()])",
            "        operations.append(previous)",
            "    operations.append([*prefix, 'top', 'pod', args.pod_name, '-n', args.namespace])",
            "    return operations",
            "",
            "",
            "def _markdown_report(namespace: str, pod_name: str, results: dict[str, dict[str, Any]]) -> str:",
            "    summary = []",
            "    if results.get('pod_json', {}).get('returncode') == 0:",
            "        summary.append('Pod metadata collected successfully.')",
            "    else:",
            "        summary.append('Pod metadata collection failed.')",
            "    if results.get('events', {}).get('returncode') == 0:",
            "        summary.append('Recent events collected successfully.')",
            "    if results.get('logs', {}).get('returncode') == 0:",
            "        summary.append('Current container logs collected successfully.')",
            "    lines = [",
            "        '# Kubernetes Incident Report',",
            "        '',",
            "        f'**Namespace**: {namespace}',",
            "        f'**Pod**: {pod_name}',",
            "        f'**Generated At**: {datetime.now(timezone.utc).isoformat()}',",
            "        '',",
            "        '## Summary',",
            "        *[f'- {item}' for item in summary],",
            "        '',",
            "        '## Pod Status',",
            "        '```json',",
            "        results.get('pod_json', {}).get('stdout', '').strip(),",
            "        '```',",
            "        '',",
            "        '## Recent Events',",
            "        '```text',",
            "        results.get('events', {}).get('stdout', '').strip(),",
            "        '```',",
            "        '',",
            "        '## Logs',",
            "        '```text',",
            "        results.get('logs', {}).get('stdout', '').strip(),",
            "        '```',",
            "        '',",
            "        '## Recommendations',",
            "        '- Review describe output for readiness, liveness, and image pull failures.',",
            "        '- Correlate warning events with recent log timestamps.',",
            "        '- Re-run with --include-previous when the pod is crash looping.',",
            "    ]",
            "    if results.get('previous_logs'):",
            "        lines.extend(['', '## Previous Logs', '```text', results['previous_logs'].get('stdout', '').strip(), '```'])",
            "    return '\\n'.join(lines).strip() + '\\n'",
            "",
            "",
            "def main() -> int:",
            "    args = build_parser().parse_args()",
            "    output_path, bundle_path = _output_paths(args.output_path, args.bundle_path, args.namespace, args.pod_name or 'pod')",
            "    planned = _planned_operations(args)",
            "    if args.dry_run or not args.pod_name.strip():",
            "        payload = {",
            "            'capability': CAPABILITY_NAME,",
            "            'target_path': TARGET_PATH,",
            "            'dry_run': True,",
            "            'namespace': args.namespace,",
            "            'pod_name': args.pod_name,",
            "            'context': args.context,",
            "            'planned_operations': planned,",
            "            'implementation_contract': IMPLEMENTATION_CONTRACT,",
            "            'report_path': str(output_path),",
            "            'bundle_path': str(bundle_path),",
            "        }",
            "        print(json.dumps(payload, ensure_ascii=False, indent=2))",
            "        return 0",
            "",
            "    results = {",
            "        'pod_json': _run_kubectl(planned[0]),",
            "        'describe': _run_kubectl(planned[1]),",
            "        'events': _run_kubectl(planned[2]),",
            "        'logs': _run_kubectl(planned[3]),",
            "    }",
            "    if len(planned) >= 5 and '--previous' in planned[4]:",
            "        results['previous_logs'] = _run_kubectl(planned[4])",
            "        top_index = 5",
            "    else:",
            "        top_index = 4",
            "    if len(planned) > top_index:",
            "        results['top'] = _run_kubectl(planned[top_index])",
            "",
            "    output_path.parent.mkdir(parents=True, exist_ok=True)",
            "    bundle_path.parent.mkdir(parents=True, exist_ok=True)",
            "    markdown = _markdown_report(args.namespace, args.pod_name, results)",
            "    output_path.write_text(markdown, encoding='utf-8')",
            "    bundle_path.write_text(",
            "        json.dumps(",
            "            {",
            "                'capability': CAPABILITY_NAME,",
            "                'namespace': args.namespace,",
            "                'pod_name': args.pod_name,",
            "                'context': args.context,",
            "                'time_window': args.time_window,",
            "                'report_path': str(output_path),",
            "                'results': results,",
            "                'implementation_contract': IMPLEMENTATION_CONTRACT,",
            "            },",
            "            indent=2,",
            "            ensure_ascii=False,",
            "        ) + '\\n',",
            "        encoding='utf-8',",
            "    )",
            "    return 0 if all(value.get('returncode', 1) == 0 for value in results.values() if isinstance(value, dict)) else 1",
            "",
            "",
            "if __name__ == '__main__':",
            "    raise SystemExit(main())",
            "",
        ]
    )
