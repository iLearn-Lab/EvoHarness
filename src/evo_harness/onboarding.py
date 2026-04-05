from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from evo_harness.harness.provider import detect_provider_profile


@dataclass(slots=True)
class InitResult:
    workspace: str
    created_files: list[str] = field(default_factory=list)
    existing_files: list[str] = field(default_factory=list)
    provider_profile: str = ""
    model: str = ""
    next_steps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def initialize_workspace(
    workspace: str | Path,
    *,
    provider_profile: str = "anthropic",
    model: str = "",
    api_key_env: str | None = None,
    base_url: str | None = None,
    force: bool = False,
) -> InitResult:
    root = Path(workspace).resolve()
    root.mkdir(parents=True, exist_ok=True)
    profile = detect_provider_profile(profile=provider_profile)
    resolved_model = model.strip() or _default_model_for_profile(profile.name)
    created_files: list[str] = []
    existing_files: list[str] = []

    settings_path = root / ".evo-harness" / "settings.json"
    claude_md = root / "CLAUDE.md"
    commands_dir = root / ".claude" / "commands"
    agents_dir = root / ".claude" / "agents"
    skills_dir = root / ".claude" / "skills"
    mcp_path = root / ".evo-harness" / "mcp.json"
    gitignore_path = root / ".evo-harness" / ".gitignore"

    _write_if_missing(
        claude_md,
        _starter_claude_md(root.name),
        force=force,
        created=created_files,
        existing=existing_files,
    )
    _write_if_missing(
        settings_path,
        json.dumps(
            _starter_settings(
                profile_name=profile.name,
                model=resolved_model,
                api_key_env=api_key_env or profile.default_api_key_env,
                base_url=base_url or profile.default_base_url,
                api_format=profile.api_format,
                auth_scheme=profile.auth_scheme,
            ),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        force=force,
        created=created_files,
        existing=existing_files,
    )
    _write_if_missing(
        commands_dir / "inspect-repo.md",
        _starter_command(),
        force=force,
        created=created_files,
        existing=existing_files,
    )
    _write_if_missing(
        commands_dir / "context-pressure.md",
        _starter_context_pressure_command(),
        force=force,
        created=created_files,
        existing=existing_files,
    )
    _write_if_missing(
        commands_dir / "validation-gate.md",
        _starter_validation_gate_command(),
        force=force,
        created=created_files,
        existing=existing_files,
    )
    _write_if_missing(
        agents_dir / "explorer.md",
        _starter_agent(),
        force=force,
        created=created_files,
        existing=existing_files,
    )
    _write_if_missing(
        agents_dir / "validator.md",
        _starter_validator_agent(),
        force=force,
        created=created_files,
        existing=existing_files,
    )
    _write_if_missing(
        agents_dir / "context-curator.md",
        _starter_context_agent(),
        force=force,
        created=created_files,
        existing=existing_files,
    )
    _write_if_missing(
        skills_dir / "long-context-retrieval.md",
        _starter_long_context_skill(),
        force=force,
        created=created_files,
        existing=existing_files,
    )
    _write_if_missing(
        skills_dir / "validation-gating.md",
        _starter_validation_skill(),
        force=force,
        created=created_files,
        existing=existing_files,
    )
    _write_if_missing(
        skills_dir / "self-evolution-triage.md",
        _starter_self_evolution_skill(),
        force=force,
        created=created_files,
        existing=existing_files,
    )
    _write_if_missing(
        skills_dir / "plugin-authoring.md",
        _starter_plugin_authoring_skill(),
        force=force,
        created=created_files,
        existing=existing_files,
    )
    _write_if_missing(
        agents_dir / "plugin-architect.md",
        _starter_plugin_architect_agent(),
        force=force,
        created=created_files,
        existing=existing_files,
    )
    _write_if_missing(
        commands_dir / "plugin-blueprint.md",
        _starter_plugin_blueprint_command(),
        force=force,
        created=created_files,
        existing=existing_files,
    )
    _write_if_missing(
        mcp_path,
        json.dumps(_starter_mcp_config(), indent=2, ensure_ascii=False) + "\n",
        force=force,
        created=created_files,
        existing=existing_files,
    )
    _write_if_missing(
        gitignore_path,
        _starter_gitignore(),
        force=force,
        created=created_files,
        existing=existing_files,
    )

    next_steps = [
        f"Set your API key env var: {api_key_env or profile.default_api_key_env}",
        "Edit CLAUDE.md and add your real project instructions and test commands.",
        "Review .evo-harness/settings.json and adjust model / provider / sandbox settings if needed.",
        "Run `evoh doctor --workspace .` inside your repo.",
        "Start the dashboard with `evoh --workspace .`.",
    ]

    return InitResult(
        workspace=str(root),
        created_files=created_files,
        existing_files=existing_files,
        provider_profile=profile.name,
        model=resolved_model,
        next_steps=next_steps,
    )


def _write_if_missing(
    path: Path,
    content: str,
    *,
    force: bool,
    created: list[str],
    existing: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        existing.append(str(path))
        return
    path.write_text(content, encoding="utf-8")
    created.append(str(path))


def _default_model_for_profile(profile_name: str) -> str:
    defaults = {
        "anthropic": "claude-sonnet-4",
        "anthropic-compatible": "claude-sonnet-4",
        "vertex-anthropic": "claude-sonnet-4",
        "bedrock-compatible": "claude-sonnet-4",
        "openai": "gpt-4.1-mini",
        "openai-compatible": "gpt-4.1-mini",
        "moonshot": "kimi-k2.5",
    }
    return defaults.get(profile_name, "claude-sonnet-4")


def _starter_claude_md(project_name: str) -> str:
    return "\n".join(
        [
            "# Project Instructions",
            "",
            f"- Project: {project_name}",
            "- Start with the smallest useful inspection before editing.",
            "- Prefer focused changes over broad rewrites.",
            "- Validate the affected area before claiming success.",
            "- Call out risks, assumptions, and follow-up checks.",
            "",
            "## Validation",
            "",
            "- Replace this section with your real build/test commands.",
            "- Example: `pytest -q`",
            "",
            "## Local Notes",
            "",
            "- Add stack-specific rules, coding style, and release constraints here.",
            "",
        ]
    ) + "\n"


def _starter_settings(
    *,
    profile_name: str,
    model: str,
    api_key_env: str,
    base_url: str,
    api_format: str,
    auth_scheme: str,
) -> dict[str, Any]:
    return {
        "model": model,
        "provider": {
            "provider": profile_name,
            "profile": profile_name,
            "api_format": api_format,
            "api_key_env": api_key_env,
            "base_url": base_url,
            "auth_scheme": auth_scheme,
        },
        "query": {
            "max_turns": 12,
            "max_total_tool_calls": 30,
            "max_tool_failures": 8,
        },
        "sandbox": {
            "mode": "workspace-write",
            "allow_network": True,
            "block_bash_by_default": False,
        },
        "approvals": {
            "mode": "queue",
            "cache_approved_actions": True,
            "cache_denied_actions": True,
        },
        "permission": {
            "mode": "default",
            "allowed_tools": [],
            "denied_tools": [],
            "path_rules": [],
            "denied_commands": [],
        },
    }


def _starter_command() -> str:
    return "\n".join(
        [
            "---",
            "description: Inspect the repository before making changes",
            "argument-hint: Focus area",
            "allowed-tools: read_file,grep,glob,list_registry,workspace_status",
            "---",
            "",
            "# Inspect Repo",
            "",
            "You are inspecting this repository before editing.",
            "",
            "Focus: $ARGUMENTS",
            "",
            "## Workflow",
            "",
            "1. Read the nearest `CLAUDE.md` first.",
            "2. Search for the relevant implementation area.",
            "3. Summarize what matters before proposing edits.",
            "",
        ]
    ) + "\n"


def _starter_agent() -> str:
    return "\n".join(
        [
            "---",
            "description: Explore the repository and summarize the relevant code paths",
            "tools: read_file,grep,glob,list_registry",
            "parallel-safe: true",
            "---",
            "",
            "# Explorer Agent",
            "",
            "- Map the relevant files and implementation paths.",
            "- Stay read-only unless the parent explicitly changes mode.",
            "- Summarize what matters for the task at hand.",
            "",
        ]
    ) + "\n"


def _starter_validator_agent() -> str:
    return "\n".join(
        [
            "---",
            "description: Review whether a proposed change has enough replay, regression, and rollback safety",
            "tools: read_file,grep,glob,list_registry,workspace_status",
            "parallel-safe: true",
            "---",
            "",
            "# Validator Agent",
            "",
            "- Check replay, regression, and rollback expectations.",
            "- Prefer specific missing gates over vague safety comments.",
            "- Summarize what should block promotion.",
            "",
        ]
    ) + "\n"


def _starter_context_agent() -> str:
    return "\n".join(
        [
            "---",
            "description: Narrow large files and broad searches into the smallest useful continuation window",
            "tools: read_file,grep,glob,list_registry,workspace_status",
            "parallel-safe: true",
            "---",
            "",
            "# Context Curator",
            "",
            "- Shrink the search space before the parent keeps reading.",
            "- Prefer exact windows and targeted follow-up reads.",
            "- End with the minimum file/segment set worth continuing from.",
            "",
        ]
    ) + "\n"


def _starter_long_context_skill() -> str:
    return "\n".join(
        [
            "---",
            "name: long-context-retrieval",
            "description: Read large files and search results progressively instead of flooding the conversation.",
            "---",
            "",
            "# Long Context Retrieval",
            "",
            "- Use `grep` before broad `read_file` calls when the target window is unclear.",
            "- Follow `next segment` and `next offset` hints instead of re-reading everything.",
            "- Stop exploring once you have enough evidence to explain or act.",
            "",
        ]
    ) + "\n"


def _starter_validation_skill() -> str:
    return "\n".join(
        [
            "---",
            "name: validation-gating",
            "description: Keep harness changes candidate-first, replayable, and rollback-safe.",
            "---",
            "",
            "# Validation Gating",
            "",
            "- Candidate first, promotion second.",
            "- Record replay, regression, and rollback expectations.",
            "- Do not call a change safe if those gates are still implicit.",
            "",
        ]
    ) + "\n"


def _starter_self_evolution_skill() -> str:
    return "\n".join(
        [
            "---",
            "name: self-evolution-triage",
            "description: Decide whether a trace should stop, distill memory, revise a command, or revise a skill.",
            "---",
            "",
            "# Self Evolution Triage",
            "",
            "- Prefer `stop` when the signal is weak.",
            "- Prefer `distill_memory` on reusable success.",
            "- Prefer `revise_command` when command policy or recovery flow is the problem.",
            "- Prefer `revise_skill` when the workflow keeps looping or misusing tools.",
            "",
        ]
    ) + "\n"


def _starter_plugin_authoring_skill() -> str:
    return "\n".join(
        [
            "---",
            "name: plugin-authoring",
            "description: Package commands, skills, agents, and MCP as one coherent plugin bundle.",
            "---",
            "",
            "# Plugin Authoring",
            "",
            "- Treat a plugin as a user-facing workflow bundle, not just a folder.",
            "- Keep manifest metadata aligned with the bundle contents.",
            "- Make MCP boot paths real before counting the plugin as shipped.",
            "",
        ]
    ) + "\n"


def _starter_context_pressure_command() -> str:
    return "\n".join(
        [
            "---",
            "description: Diagnose long-search and large-file pressure",
            "argument-hint: Pressure source",
            "allowed-tools: read_file,grep,glob,list_registry,workspace_status,skill",
            "---",
            "",
            "# Context Pressure",
            "",
            "Target: $ARGUMENTS",
            "",
            "1. Load `long-context-retrieval` first.",
            "2. Narrow the search space before reading more files.",
            "3. End with the next best continuation window.",
            "",
        ]
    ) + "\n"


def _starter_plugin_architect_agent() -> str:
    return "\n".join(
        [
            "---",
            "description: Review plugin bundle shape, discovery quality, and MCP wiring",
            "tools: read_file,grep,glob,list_registry,workspace_status",
            "parallel-safe: true",
            "---",
            "",
            "# Plugin Architect",
            "",
            "- Inspect manifests, bundle boundaries, and registry naming.",
            "- Prefer plugin changes that improve daily discoverability.",
            "- Finish with the leanest plugin patch worth making now.",
            "",
        ]
    ) + "\n"


def _starter_validation_gate_command() -> str:
    return "\n".join(
        [
            "---",
            "description: Review whether a candidate change is ready for promotion",
            "argument-hint: Candidate or workflow",
            "allowed-tools: read_file,grep,glob,list_registry,workspace_status,skill",
            "---",
            "",
            "# Validation Gate",
            "",
            "Candidate: $ARGUMENTS",
            "",
            "1. Load `validation-gating` first.",
            "2. Check replay, regression, and rollback expectations.",
            "3. Conclude what is safe now and what still blocks promotion.",
            "",
        ]
    ) + "\n"


def _starter_plugin_blueprint_command() -> str:
    return "\n".join(
        [
            "---",
            "description: Design a plugin bundle that adds real harness value",
            "argument-hint: Plugin concept or gap",
            "allowed-tools: read_file,grep,glob,list_registry,workspace_status,skill",
            "---",
            "",
            "# Plugin Blueprint",
            "",
            "Target: $ARGUMENTS",
            "",
            "1. Load `plugin-authoring` first.",
            "2. Inspect what commands, skills, agents, and MCP the plugin should actually own.",
            "3. End with the leanest coherent bundle worth shipping.",
            "",
        ]
    ) + "\n"


def _starter_mcp_config() -> dict[str, Any]:
    return {
        "mcpServers": {
            "workspace-docs": {
                "transport": "stdio",
                "command": "python",
                "args": ["-m", "evo_harness.workspace_docs_mcp_server"],
                "description": "Local documentation MCP server for the workspace.",
            },
            "workspace-intel": {
                "transport": "stdio",
                "command": "python",
                "args": ["-m", "evo_harness.workspace_intel_mcp_server"],
                "description": "Workspace surface inspection MCP server.",
            }
        }
    }


def _starter_gitignore() -> str:
    return "\n".join(
        [
            "sessions/",
            "tasks/",
            "executions/",
            "approvals/",
            "benchmarks/",
            "candidates/",
            "rollbacks/",
            "*.local.json",
            "",
        ]
    )
