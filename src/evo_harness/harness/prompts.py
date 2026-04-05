from __future__ import annotations

from pathlib import Path

from evo_harness.core.workspace import discover_workspace
from evo_harness.harness.content_windows import context_safe_output
from evo_harness.harness.agents import load_workspace_agents
from evo_harness.harness.commands import load_workspace_commands
from evo_harness.harness.environment import EnvironmentInfo, get_environment_info
from evo_harness.harness.memory import (
    find_relevant_memory_entries,
    load_memory_prompt,
    render_memory_entry,
)
from evo_harness.harness.mcp import load_mcp_registry
from evo_harness.harness.plugins import load_workspace_plugins
from evo_harness.harness.settings import HarnessSettings, load_settings
from evo_harness.harness.skills import load_workspace_skills


_BASE_SYSTEM_PROMPT = """\
You are an AI assistant integrated into a terminal-first agent harness.
You help users with software engineering tasks including code understanding,
editing, debugging, command execution, and workflow coordination.

Prefer concrete actions over generic advice.
Respect workspace instructions, safety boundaries, and validation requirements.
"""


def build_system_prompt(
    workspace: str | Path,
    *,
    custom_prompt: str | None = None,
    env: EnvironmentInfo | None = None,
    settings: HarnessSettings | None = None,
    latest_user_prompt: str | None = None,
    max_chars_per_file: int = 8000,
) -> str:
    resolved = Path(workspace).resolve()
    env = env or get_environment_info(resolved)
    settings = settings or load_settings(workspace=resolved)
    workspace_view = discover_workspace(resolved)
    skills = load_workspace_skills(resolved)
    agents = load_workspace_agents(resolved)
    commands = load_workspace_commands(resolved, settings=settings)
    plugins = load_workspace_plugins(resolved, settings=settings)
    mcp_registry = load_mcp_registry(resolved, settings=settings)

    sections = [
        custom_prompt if custom_prompt is not None else _BASE_SYSTEM_PROMPT,
        _format_environment_section(env),
        _format_guardrail_section(settings),
        _format_discovery_section(
            skills=skills,
            agents=agents,
            commands=commands,
            plugins=plugins,
            mcp_server_count=len(mcp_registry.servers),
        ),
    ]

    if workspace_view.claude_files:
        sections.append(_load_instruction_section(workspace_view.claude_files, max_chars_per_file))

    memory_section = load_memory_prompt(resolved, max_chars=max_chars_per_file)
    if memory_section:
        sections.append(memory_section)

    if latest_user_prompt:
        relevant_memory = _format_relevant_memory_section(
            latest_user_prompt,
            workspace=resolved,
            max_chars_per_file=max_chars_per_file,
        )
        if relevant_memory:
            sections.append(relevant_memory)

    if skills:
        sections.append(_format_skill_section(skills))

    if agents:
        sections.append(_format_agent_section(agents))

    if commands:
        sections.append(_format_command_section(commands))

    if plugins:
        sections.append(_format_plugin_section(plugins))

    if mcp_registry.servers:
        sections.append(_format_mcp_section(mcp_registry))

    return "\n\n".join(section for section in sections if section.strip())


def _format_environment_section(env: EnvironmentInfo) -> str:
    lines = [
        "# Environment",
        f"- OS: {env.os_name} {env.os_version}",
        f"- Architecture: {env.platform_machine}",
        f"- Shell: {env.shell}",
        f"- Working directory: {env.cwd}",
        f"- Date: {env.date}",
        f"- Python: {env.python_version}",
    ]
    if env.is_git_repo:
        git_line = "- Git: yes"
        if env.git_branch:
            git_line += f" (branch: {env.git_branch})"
        lines.append(git_line)
    return "\n".join(lines)


def _load_instruction_section(paths: list[str], max_chars_per_file: int) -> str:
    lines = ["# Project Instructions"]
    for path_str in paths:
        path = Path(path_str)
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars_per_file:
            content, _metadata = context_safe_output(content, limit=max_chars_per_file)
        lines.extend(["", f"## {path}", "```md", content.strip(), "```"])
    return "\n".join(lines)


def _load_memory_section(path_str: str, max_chars_per_file: int) -> str:
    path = Path(path_str)
    content = path.read_text(encoding="utf-8", errors="replace")
    if len(content) > max_chars_per_file:
        content, _metadata = context_safe_output(content, limit=max_chars_per_file)
    return "\n".join(["# Persistent Memory", "```md", content.strip(), "```"])


def _format_skill_section(skills: list) -> str:
    lines = [
        "# Available Skills",
        "Use the `skill` tool to load the full instructions for a skill before following it in detail.",
    ]
    for skill in skills[:20]:
        lines.append(f"- {skill.name}: {skill.description}")
    return "\n".join(lines)


def _format_agent_section(agents: list) -> str:
    lines = ["# Available Agents"]
    for agent in agents[:20]:
        lines.append(f"- {agent.name}: {agent.description}")
    return "\n".join(lines)


def _format_command_section(commands: list) -> str:
    lines = ["# Available Commands"]
    for command in commands[:20]:
        allowed_tools = ""
        if command.allowed_tools:
            allowed_tools = f" [tools: {', '.join(command.allowed_tools)}]"
        lines.append(f"- {command.name}: {command.description}{allowed_tools}")
    return "\n".join(lines)


def _format_plugin_section(plugins: list) -> str:
    lines = ["# Installed Plugins"]
    for plugin in plugins[:20]:
        lines.append(f"- {plugin.manifest.name}: {plugin.manifest.description}")
    return "\n".join(lines)


def _format_guardrail_section(settings: HarnessSettings) -> str:
    lines = [
        "# Runtime Guardrails",
        f"- Query max turns: {settings.query.max_turns}",
        f"- Query max total tool calls: {settings.query.max_total_tool_calls}",
        f"- Query max tool failures: {settings.query.max_tool_failures}",
        f"- Safety max mutating tools: {settings.safety.max_mutating_tools_per_query}",
        f"- Safety blocked shell patterns: {', '.join(settings.safety.blocked_shell_patterns[:4])}",
    ]
    return "\n".join(lines)


def _format_discovery_section(
    *,
    skills: list,
    agents: list,
    commands: list,
    plugins: list,
    mcp_server_count: int,
) -> str:
    lines = [
        "# Harness Discovery Workflow",
        "- When the workspace is unfamiliar, start with `workspace_status` or `list_registry`.",
        "- Use `tool_help` before using unfamiliar tools.",
        "- If a relevant skill is listed, call the `skill` tool and follow the loaded instructions.",
        "- If a relevant command is listed, prefer activating or rendering it instead of improvising.",
        "- For large files, use `read_file` progressively with `segment` or `start_line`/`end_line` instead of dumping the whole file in one read.",
        "- For broad searches, use `grep` with paginated follow-up reads via `offset` and `limit`.",
        "- If agents are available, use `run_subagent` for bounded exploration, review, or comparison work.",
    ]
    if mcp_server_count:
        lines.append("- If MCP assets are available, prefer MCP tools/resources/prompts when they match the task.")
    lines.extend(
        [
            f"- Skills available: {len(skills)}",
            f"- Commands available: {len(commands)}",
            f"- Agents available: {len(agents)}",
            f"- Plugins installed: {len(plugins)}",
            f"- MCP servers available: {mcp_server_count}",
        ]
    )
    return "\n".join(lines)


def _format_mcp_section(mcp_registry) -> str:
    lines = ["# MCP Registry"]
    for server in mcp_registry.servers[:10]:
        lines.append(
            f"- {server.name}: transport={server.transport} tools={len(server.tools)} resources={len(server.resources)} prompts={len(server.prompts)}"
        )
    return "\n".join(lines)


def _format_relevant_memory_section(
    latest_user_prompt: str,
    *,
    workspace: str | Path,
    max_chars_per_file: int,
) -> str | None:
    entries = find_relevant_memory_entries(latest_user_prompt, workspace)
    if not entries:
        return None
    lines = ["# Relevant Memories"]
    for path in entries:
        lines.extend(
            [
                "",
                f"## {path.name}",
                "```md",
                render_memory_entry(path, max_chars=max_chars_per_file),
                "```",
            ]
        )
    return "\n".join(lines)
