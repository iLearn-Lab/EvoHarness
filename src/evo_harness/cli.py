from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

from evo_harness.adapters import ClaudeCodeAdapter, OpenHarnessAdapter
from evo_harness.benchmark import (
    build_provider_factory,
    compare_benchmark_runs,
    run_benchmark,
    write_benchmark_run,
)
from evo_harness.engine import EvolutionEngine
from evo_harness.execution import (
    ControlledEvolutionExecutor,
    list_execution_records,
    promotion_analytics_report,
    promotion_report,
    rollback_execution,
    write_execution_record,
)
from evo_harness.harness import (
    ConversationEngine,
    HarnessRuntime,
    PermissionChecker,
    ScriptedProvider,
    add_memory_entry,
    build_system_prompt,
    find_agent,
    load_workspace_plugins,
    find_command,
    get_environment_info,
    load_marketplaces,
    install_marketplace_plugin,
    list_memory_entries,
    load_settings,
    load_workspace_commands,
    load_workspace_hooks,
    load_workspace_skills,
    load_workspace_agents,
    plan_from_saved_session,
    remove_memory_entry,
    run_query,
    run_subagent,
    get_task_manager,
    load_workflow,
    run_workflow,
    list_session_snapshots,
    load_session_snapshot,
    export_session_markdown,
    build_live_provider,
    detect_provider_profile,
    list_mcp_prompts,
    list_mcp_resources,
    list_mcp_servers,
    list_mcp_tools,
    list_provider_profiles,
    launch_react_tui,
    run_query_stream,
    run_backend_host,
    run_home_ui,
    run_interactive_repl,
    save_settings,
    session_analytics_report,
)
from evo_harness.harness.console import enable_utf8_console
from evo_harness.models import HarnessCapabilities, TaskTrace
from evo_harness.onboarding import initialize_workspace
from evo_harness.storage import EvolutionLedger


def _load_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _load_jsonish_arg(value: str) -> dict:
    text = value.strip()
    if text.startswith("@"):
        return _load_json(text[1:])
    return json.loads(text)


def _load_capabilities(path: str | Path) -> HarnessCapabilities:
    payload = _load_json(path)
    adapter_name = payload.get("adapter_name", "generic")
    if adapter_name == "openharness":
        return OpenHarnessAdapter().capabilities_from_manifest(payload)
    if adapter_name == "claude-code":
        return ClaudeCodeAdapter().capabilities_from_manifest(payload)
    return HarnessCapabilities.from_dict(payload)


def _print_human(plan: dict) -> None:
    proposal = plan["proposal"]
    print(f"Harness: {plan['trace']['harness']}")
    print(f"Task: {plan['trace']['task_id']}")
    print(f"Operator: {proposal['operator']}")
    print(f"Safe To Apply: {'yes' if plan['safe_to_apply'] else 'no'}")
    print(f"Reason: {proposal['reason']}")
    print("\nValidation Steps:")
    for step in proposal["validator_steps"]:
        print(f"- {step}")
    print("\nWorkspace:")
    print(f"- CLAUDE files: {len(plan['workspace']['claude_files'])}")
    print(f"- Memory files: {len(plan['workspace']['memory_files'])}")
    print(f"- Skill files: {len(plan['workspace']['skill_files'])}")
    print(f"- Hook files: {len(plan['workspace']['hook_files'])}")
    print("\nChange Request:")
    print(json.dumps(plan["change_request"], indent=2, ensure_ascii=False))


def _build_doctor_report(workspace: str | Path, *, settings_path: str | Path | None = None) -> dict[str, object]:
    from evo_harness.core.workspace import discover_workspace
    from evo_harness.harness import call_mcp_method

    runtime = HarnessRuntime(workspace, settings_path=settings_path)
    workspace_view = discover_workspace(workspace)
    skills = runtime.list_skills()
    commands = runtime.list_commands()
    agents = runtime.list_agents()
    plugins = runtime.list_plugins()
    mcp_servers = runtime.list_mcp_servers()
    session_report = session_analytics_report(workspace, limit=20)
    warnings: list[str] = []
    notes: list[str] = []
    recommendations: list[str] = []

    if not workspace_view.claude_files:
        warnings.append("No CLAUDE.md-style workspace instructions were found.")
    tool_names = {str(item["name"]) for item in runtime.list_tools()}
    plugin_names = {str(item["manifest"]["name"]) for item in plugins}

    command_health: list[dict[str, object]] = []
    for command in commands:
        missing_tools = sorted(
            tool_name
            for tool_name in (command.get("allowed_tools") or [])
            if tool_name not in tool_names
        )
        missing_plugins = sorted(
            plugin_name
            for plugin_name in (command.get("requires_plugins") or [])
            if plugin_name not in plugin_names
        )
        if missing_tools or missing_plugins:
            command_health.append(
                {
                    "name": command.get("name"),
                    "path": command.get("path"),
                    "missing_tools": missing_tools,
                    "missing_plugins": missing_plugins,
                }
            )

    agent_health: list[dict[str, object]] = []
    for agent in agents:
        missing_tools = sorted(
            tool_name
            for tool_name in (agent.get("tools") or [])
            if tool_name not in tool_names
        )
        if missing_tools:
            agent_health.append(
                {
                    "name": agent.get("name"),
                    "path": agent.get("path"),
                    "missing_tools": missing_tools,
                }
            )

    plugin_health: list[dict[str, object]] = []
    for plugin in plugins:
        manifest = dict(plugin.get("manifest", {}))
        plugin_path = Path(str(plugin.get("path", "")))
        commands_dir = plugin_path / str(manifest.get("commands_dir", "commands"))
        skills_dir = plugin_path / str(manifest.get("skills_dir", "skills"))
        agents_dir = plugin_path / str(manifest.get("agents_dir", "agents"))
        mcp_file = plugin_path / str(manifest.get("mcp_file", ".mcp.json"))
        missing_paths = []
        if not commands_dir.exists():
            missing_paths.append(str(commands_dir))
        if not skills_dir.exists():
            missing_paths.append(str(skills_dir))
        if not agents_dir.exists():
            missing_paths.append(str(agents_dir))
        if not mcp_file.exists():
            missing_paths.append(str(mcp_file))
        warnings_for_plugin = list(plugin.get("warnings", []))
        plugin_health.append(
            {
                "name": manifest.get("name"),
                "path": str(plugin_path),
                "source": plugin.get("source"),
                "warnings": warnings_for_plugin,
                "missing_paths": missing_paths,
                "counts": {
                    "commands": len(list(commands_dir.glob("*.md"))) if commands_dir.exists() else 0,
                    "skills": len(list(skills_dir.glob("*.md"))) if skills_dir.exists() else 0,
                    "agents": len(list(agents_dir.glob("*.md"))) if agents_dir.exists() else 0,
                    "has_mcp_file": mcp_file.exists(),
                },
                "status": "ok" if not warnings_for_plugin and not missing_paths else "warning",
            }
        )

    mcp_health: list[dict[str, object]] = []
    for server in mcp_servers:
        declared_tools = len(server.get("tools", []))
        declared_resources = len(server.get("resources", []))
        declared_prompts = len(server.get("prompts", []))
        status = "skipped"
        error = ""
        live_tools = 0
        live_resources = 0
        live_prompts = 0
        transport = str(server.get("transport", ""))
        if transport == "stdio":
            try:
                tool_payload = call_mcp_method(
                    runtime.workspace,
                    server_name=str(server["name"]),
                    method="tools/list",
                    params={},
                ).payload
                resource_payload = call_mcp_method(
                    runtime.workspace,
                    server_name=str(server["name"]),
                    method="resources/list",
                    params={},
                ).payload
                prompt_payload = call_mcp_method(
                    runtime.workspace,
                    server_name=str(server["name"]),
                    method="prompts/list",
                    params={},
                ).payload
                live_tools = len(tool_payload.get("tools", []))
                live_resources = len(resource_payload.get("resources", []))
                live_prompts = len(prompt_payload.get("prompts", []))
                status = "ok"
            except Exception as exc:
                status = "error"
                error = str(exc)
        elif transport in {"http", "https", "streamable-http"}:
            status = "remote_not_checked"
            error = "Remote MCP servers are not probed automatically by doctor."
        else:
            status = "unsupported_transport"
            error = f"Unsupported transport: {transport}"
        mcp_health.append(
            {
                "name": server.get("name"),
                "transport": transport,
                "source": server.get("source"),
                "status": status,
                "declared": {
                    "tools": declared_tools,
                    "resources": declared_resources,
                    "prompts": declared_prompts,
                },
                "live": {
                    "tools": live_tools,
                    "resources": live_resources,
                    "prompts": live_prompts,
                },
                "error": error,
            }
        )

    if not commands:
        warnings.append("No commands were discovered; command workflows are still shallow.")
    if not agents:
        warnings.append("No agents were discovered; delegation is not fully available.")
    if not skills:
        warnings.append("No skills were discovered; reusable workflow guidance is still thin.")
    if len(runtime.list_tools()) < 15:
        warnings.append("Tool registry is still relatively small for a full coding harness.")
    if runtime.settings.permission.mode == "default":
        notes.append("Permission mode is default, so mutating tools still require confirmation while common safe shell reads can run directly.")
    if not plugins:
        notes.append("No enabled plugins are loaded. Plugin settings and marketplace flows may be underused.")
    if not mcp_servers:
        warnings.append("No MCP servers are registered, so external tool/resource/prompt ecosystems are still shallow.")
    if runtime.settings.query.max_context_messages < 12:
        warnings.append("Query context window is configured quite tightly and may truncate useful history.")
    if runtime.settings.safety.max_mutating_tools_per_query < 4:
        warnings.append("Mutation safety budget is very low and may stop legitimate coding sessions early.")
    if session_report["totals"]["sessions"] < 3:
        notes.append("Session history is still sparse; promotion analytics will get stronger after more runs.")
    if command_health:
        warnings.append(f"{len(command_health)} commands reference missing tools or required plugins.")
    if agent_health:
        warnings.append(f"{len(agent_health)} agents reference missing tools.")
    if any(item["status"] == "warning" for item in plugin_health):
        warnings.append("Some plugins have missing bundle paths or dependency warnings.")
    if any(item["status"] == "error" for item in mcp_health):
        warnings.append("Some local MCP servers failed the doctor handshake.")
    if not commands:
        recommendations.append("Add or refine markdown commands to package repeatable workflows.")
    if not mcp_servers:
        recommendations.append("Add an MCP registry file (.mcp.json or .evo-harness/mcp.json) to expose external tools/resources/prompts.")
    if command_health or agent_health:
        recommendations.append("Fix missing tool references so commands and agents only advertise callable capabilities.")
    if any(item["status"] == "error" for item in mcp_health):
        recommendations.append("Repair failing MCP servers before counting them as part of the live harness surface.")
    if session_report["totals"]["sessions"] < 3:
        recommendations.append("Keep archived sessions enabled so evolution can learn from multiple runs, not just the latest one.")

    return {
        "workspace": str(Path(workspace).resolve()),
        "model": runtime.settings.model,
        "permission_mode": runtime.settings.permission.mode,
        "provider": _provider_report(runtime.settings),
        "counts": {
            "tools": len(runtime.list_tools()),
            "commands": len(commands),
            "skills": len(skills),
            "agents": len(agents),
            "plugins": len(plugins),
            "mcp_servers": len(mcp_servers),
            "mcp_tools": len(runtime.list_mcp_tools()),
            "mcp_resources": len(runtime.list_mcp_resources()),
            "mcp_prompts": len(runtime.list_mcp_prompts()),
            "sessions": len(runtime.list_sessions()),
            "tasks": len(runtime.list_tasks()),
        },
        "health": {
            "commands": command_health,
            "agents": agent_health,
            "plugins": plugin_health,
            "mcp_servers": mcp_health,
        },
        "warnings": warnings,
        "notes": notes,
        "recommendations": recommendations,
    }


def _provider_report(settings) -> dict[str, object]:
    profile = detect_provider_profile(
        provider=settings.provider.provider,
        profile=settings.provider.profile,
        base_url=settings.provider.base_url,
        model=settings.model,
    )
    return {
        "provider": settings.provider.provider,
        "profile": profile.name,
        "api_format": profile.api_format,
        "base_url": settings.provider.base_url,
        "api_key_env": settings.provider.api_key_env,
        "model": settings.model,
    }


def _assistant_text_from_messages(messages: list[dict[str, object]]) -> str:
    chunks: list[str] = []
    for message in messages:
        if message.get("role") != "assistant":
            continue
        text = str(message.get("text", "")).strip()
        if text:
            chunks.append(text)
    return "\n\n".join(chunks).strip()


def _query_result_payload(result) -> dict[str, object]:
    return {
        "text": _assistant_text_from_messages(result.messages),
        "events": result.events,
        "messages": result.messages,
        "session_path": result.session_path,
        "provider_name": result.provider_name,
        "usage": result.usage,
        "query_stats": result.query_stats,
        "stop_reason": result.stop_reason,
        "turn_count": result.turn_count,
    }


def _print_query_text_stream(
    engine: ConversationEngine,
    *,
    prompt: str,
    provider,
    command_name: str | None = None,
    command_arguments: str = "",
    max_turns: int | None = None,
) -> None:
    saw_text = False
    for event in engine.submit_stream(
        prompt=prompt,
        provider=provider,
        command_name=command_name,
        command_arguments=command_arguments,
        max_turns=max_turns,
    ):
        event_name = event.__class__.__name__
        if event_name == "AssistantTextDelta":
            print(event.text, end="", flush=True)
            saw_text = True
        elif event_name == "ToolExecutionProgress":
            if saw_text:
                print()
                saw_text = False
            print(f"[{event.tool_name} {event.stream}] {event.output}", flush=True)
        elif event_name == "AssistantTurnComplete" and saw_text:
            print()
    if saw_text:
        print()


def _print_query_stream_json(
    engine: ConversationEngine,
    *,
    prompt: str,
    provider,
    command_name: str | None = None,
    command_arguments: str = "",
    max_turns: int | None = None,
) -> None:
    for event in engine.submit_stream(
        prompt=prompt,
        provider=provider,
        command_name=command_name,
        command_arguments=command_arguments,
        max_turns=max_turns,
    ):
        name = event.__class__.__name__
        if name == "AssistantTextDelta":
            print(json.dumps({"type": "assistant_delta", "text": event.text}, ensure_ascii=False), flush=True)
        elif name == "AssistantTurnComplete":
            message = dict(getattr(event, "message", {}) or {})
            print(
                json.dumps(
                    {
                        "type": "assistant_complete",
                        "text": str(message.get("text", "")).strip(),
                        "usage": getattr(event, "usage", {}),
                        "stop_reason": getattr(event, "stop_reason", None),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        elif name == "ToolExecutionStarted":
            print(
                json.dumps(
                    {
                        "type": "tool_started",
                        "tool_name": event.tool_name,
                        "tool_input": event.tool_input,
                        "tool_call_id": event.tool_call_id,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        elif name == "ToolExecutionCompleted":
            print(
                json.dumps(
                    {
                        "type": "tool_completed",
                        "tool_name": event.tool_name,
                        "output": event.output,
                        "is_error": event.is_error,
                        "tool_call_id": event.tool_call_id,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        elif name == "ToolExecutionProgress":
            print(
                json.dumps(
                    {
                        "type": "tool_progress",
                        "tool_name": event.tool_name,
                        "stream": event.stream,
                        "output": event.output,
                        "tool_call_id": event.tool_call_id,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    result = engine.runtime.last_query_result
    if result is not None:
        print(json.dumps({"type": "result", **_query_result_payload(result)}, ensure_ascii=False), flush=True)


def _configure_console_approvals(runtime: HarnessRuntime) -> None:
    if not sys.stdin.isatty():
        return

    def _prompt(request) -> bool:
        print()
        print(f"Approval required for `{request.tool_name}`")
        print(request.reason or "Mutating action requires approval.")
        if request.file_path:
            print(f"Path: {request.file_path}")
        if request.command:
            print(f"Command: {request.command}")
        response = input("Approve? [y/N]: ").strip().lower()
        return response in {"y", "yes"}

    runtime.approval_prompt = _prompt


def _workspace_appears_uninitialized(workspace: str | Path) -> bool:
    root = Path(workspace).resolve()
    return not any(
        candidate.exists()
        for candidate in (
            root / "CLAUDE.md",
            root / ".claude" / "commands",
            root / ".claude" / "agents",
            root / ".evo-harness" / "settings.json",
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evoh", description="Self-evolution control for agent harnesses.")
    parser.add_argument("-p", "--prompt", help="Run one prompt immediately without choosing a subcommand.")
    parser.add_argument("--workspace", help="Workspace root for default chat/prompt mode.")
    parser.add_argument("--settings", help="Optional settings.json path for default chat/prompt mode.")
    parser.add_argument("--provider-script", help="Scripted provider for default chat/prompt mode.")
    parser.add_argument("--resume", default="none", help="Session ID to resume in default chat mode. Defaults to a new session.")
    parser.add_argument("--backend-only", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--text-ui", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--output-format",
        choices=["text", "json", "stream-json"],
        default="text",
        help="Output format for default prompt mode.",
    )
    subparsers = parser.add_subparsers(dest="command", required=False)

    status = subparsers.add_parser("status", help="Inspect harness-native workspace status.")
    status.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    status.add_argument("--settings", help="Optional settings.json path.")

    prompt = subparsers.add_parser("build-prompt", help="Build a harness-style system prompt.")
    prompt.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    prompt.add_argument("--settings", help="Optional settings.json path.")

    settings_show = subparsers.add_parser("settings-show", help="Show the resolved settings hierarchy output.")
    settings_show.add_argument("--workspace", help="Optional workspace root for project and managed settings.")
    settings_show.add_argument("--settings", help="Optional extra settings.json path or inline JSON.")

    init_cmd = subparsers.add_parser("init", help="Initialize Evo Harness in your current repository.")
    init_cmd.add_argument("--workspace", default=".", help="Workspace root to initialize. Defaults to current directory.")
    init_cmd.add_argument("--provider-profile", default="anthropic", help="Provider profile to scaffold, e.g. anthropic or moonshot.")
    init_cmd.add_argument("--model", default="", help="Optional model to prefill in settings.")
    init_cmd.add_argument("--api-key-env", help="Optional API key env var override.")
    init_cmd.add_argument("--base-url", help="Optional base URL override.")
    init_cmd.add_argument("--force", action="store_true", help="Overwrite existing scaffold files.")

    providers = subparsers.add_parser("providers-list", help="List supported live provider profiles.")
    provider_detect = subparsers.add_parser("provider-detect", help="Show the resolved provider profile for this config.")
    provider_detect.add_argument("--workspace", help="Optional workspace root.")
    provider_detect.add_argument("--settings", help="Optional settings.json path.")
    provider_detect.add_argument("--model", help="Optional model override.")
    provider_detect.add_argument("--base-url", help="Optional base URL override.")
    provider_template = subparsers.add_parser("provider-template", help="Print a settings template for one provider profile.")
    provider_template.add_argument("--profile", required=True, help="Provider profile name.")
    provider_template.add_argument("--model", default="", help="Optional model name to inject.")

    tools = subparsers.add_parser("tools-list", help="List registered harness tools.")
    tools.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    tools.add_argument("--settings", help="Optional settings.json path.")

    doctor = subparsers.add_parser("doctor", help="Inspect structural gaps in the current workspace harness.")
    doctor.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    doctor.add_argument("--settings", help="Optional settings.json path.")

    approvals = subparsers.add_parser("approvals-list", help="List pending or historical approval requests.")
    approvals.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    approvals.add_argument("--settings", help="Optional settings.json path.")
    approvals.add_argument("--status", help="Optional status filter.")

    approval_decide = subparsers.add_parser("approval-decide", help="Approve or deny one queued approval request.")
    approval_decide.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    approval_decide.add_argument("--settings", help="Optional settings.json path.")
    approval_decide.add_argument("--id", required=True, help="Approval request id.")
    approval_decide.add_argument("--decision", choices=["approve", "deny"], required=True, help="Decision to apply.")
    approval_decide.add_argument("--note", default="", help="Optional note saved with the decision.")

    mcp_list = subparsers.add_parser("mcp-list", help="List MCP servers, tools, resources, or prompts.")
    mcp_list.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    mcp_list.add_argument("--settings", help="Optional settings.json path.")
    mcp_list.add_argument("--kind", choices=["servers", "tools", "resources", "prompts", "all"], default="all")

    mcp_call = subparsers.add_parser("mcp-call", help="Call one MCP method against a configured server.")
    mcp_call.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    mcp_call.add_argument("--server", required=True, help="MCP server name.")
    mcp_call.add_argument("--method", required=True, help="MCP method name, e.g. tools/list or tools/call.")
    mcp_call.add_argument("--params", default="{}", help="Inline JSON params or @file.json")

    tool_run = subparsers.add_parser("tool-run", help="Execute one builtin tool through the harness runtime.")
    tool_run.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    tool_run.add_argument("--settings", help="Optional settings.json path.")
    tool_run.add_argument("--tool", required=True, help="Tool name.")
    tool_run.add_argument("--input", help="Inline JSON object of tool arguments.")
    tool_run.add_argument("--input-file", help="Path to a JSON file of tool arguments.")

    chat_cmd = subparsers.add_parser("chat", help="Run a simple interactive chat session.")
    chat_cmd.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    chat_cmd.add_argument("--settings", help="Optional settings.json path.")
    chat_cmd.add_argument("--provider-script", help="Path to a scripted provider JSON file.")
    chat_cmd.add_argument("--resume", default="none", help="Session ID to resume or 'none'. Defaults to a new session.")

    ui_cmd = subparsers.add_parser("ui", help="Launch the terminal home UI.")
    ui_cmd.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    ui_cmd.add_argument("--settings", help="Optional settings.json path.")
    ui_cmd.add_argument("--provider-script", help="Path to a scripted provider JSON file.")

    commands = subparsers.add_parser("commands-list", help="List workspace commands.")
    commands.add_argument("--workspace", required=True, help="Workspace root to inspect.")

    command_show = subparsers.add_parser("command-show", help="Show one workspace command.")
    command_show.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    command_show.add_argument("--name", required=True, help="Command name without slash.")

    plugins = subparsers.add_parser("plugins-list", help="List discovered workspace plugins.")
    plugins.add_argument("--workspace", required=True, help="Workspace root to inspect.")

    marketplaces = subparsers.add_parser("marketplaces-list", help="List available plugin marketplaces.")
    marketplaces.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    marketplaces.add_argument("--settings", help="Optional settings.json path.")

    marketplace_plugins = subparsers.add_parser("marketplace-plugins", help="List plugins from visible marketplaces.")
    marketplace_plugins.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    marketplace_plugins.add_argument("--settings", help="Optional settings.json path.")

    marketplace_install = subparsers.add_parser("marketplace-install", help="Install one plugin from a marketplace.")
    marketplace_install.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    marketplace_install.add_argument("--settings", help="Optional settings.json path.")
    marketplace_install.add_argument("--marketplace", required=True, help="Marketplace name.")
    marketplace_install.add_argument("--plugin", required=True, help="Plugin name.")

    plugin_enable = subparsers.add_parser("plugin-enable", help="Enable a plugin in project settings.")
    plugin_enable.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    plugin_enable.add_argument("--name", required=True, help="Plugin name.")

    plugin_disable = subparsers.add_parser("plugin-disable", help="Disable a plugin in project settings.")
    plugin_disable.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    plugin_disable.add_argument("--name", required=True, help="Plugin name.")

    agents = subparsers.add_parser("agents-list", help="List discovered workspace agents and subagents.")
    agents.add_argument("--workspace", required=True, help="Workspace root to inspect.")

    agent_show = subparsers.add_parser("agent-show", help="Show one workspace agent.")
    agent_show.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    agent_show.add_argument("--name", required=True, help="Agent name.")

    run_agent_cmd = subparsers.add_parser("run-agent", help="Execute a workspace or plugin subagent.")
    run_agent_cmd.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    run_agent_cmd.add_argument("--settings", help="Optional settings.json path.")
    run_agent_cmd.add_argument("--name", required=True, help="Agent name.")
    run_agent_cmd.add_argument("--task", required=True, help="Task assigned to the subagent.")
    run_agent_cmd.add_argument("--provider-script", required=True, help="Path to a scripted provider JSON file.")
    run_agent_cmd.add_argument("--max-turns", type=int, default=8, help="Maximum provider turns.")

    run_workflow_cmd = subparsers.add_parser("run-workflow", help="Run a multi-agent workflow definition.")
    run_workflow_cmd.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    run_workflow_cmd.add_argument("--settings", help="Optional settings.json path.")
    run_workflow_cmd.add_argument("--workflow", required=True, help="Path to a workflow JSON file.")
    run_workflow_cmd.add_argument("--provider-script", required=True, help="Path to a scripted provider JSON file.")
    run_workflow_cmd.add_argument("--max-turns", type=int, default=8, help="Maximum provider turns.")

    command_render = subparsers.add_parser("command-render", help="Render one workspace command with arguments.")
    command_render.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    command_render.add_argument("--name", required=True, help="Command name without slash.")
    command_render.add_argument("--arguments", default="", help="Arguments string injected into the command.")

    run_script = subparsers.add_parser("run-script", help="Run a scripted harness session.")
    run_script.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    run_script.add_argument("--settings", help="Optional settings.json path.")
    run_script.add_argument("--script", required=True, help="Path to a script JSON file.")

    run_query_cmd = subparsers.add_parser("run-query", help="Run a provider-driven query loop.")
    run_query_cmd.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    run_query_cmd.add_argument("--settings", help="Optional settings.json path.")
    run_query_cmd.add_argument("--provider-script", required=True, help="Path to a scripted provider JSON file.")
    run_query_cmd.add_argument("--prompt", required=True, help="Initial user prompt.")
    run_query_cmd.add_argument(
        "--command-name",
        dest="query_command_name",
        help="Optional workspace command name to activate.",
    )
    run_query_cmd.add_argument(
        "--command-arguments",
        dest="query_command_arguments",
        default="",
        help="Arguments passed into the active command.",
    )
    run_query_cmd.add_argument("--max-turns", type=int, default=8, help="Maximum provider turns.")
    run_query_cmd.add_argument(
        "--output-format",
        choices=["text", "json", "stream-json"],
        default="json",
        help="Output format for the query result.",
    )

    run_live_query = subparsers.add_parser("run-live-query", help="Run a live query using a real model provider.")
    run_live_query.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    run_live_query.add_argument("--settings", help="Optional settings.json path.")
    run_live_query.add_argument("--prompt", required=True, help="Initial user prompt.")
    run_live_query.add_argument("--command-name", dest="live_command_name", help="Optional workspace command name.")
    run_live_query.add_argument(
        "--command-arguments",
        dest="live_command_arguments",
        default="",
        help="Arguments passed into the active command.",
    )
    run_live_query.add_argument(
        "--provider",
        default=None,
        help="Provider or profile name. Examples: anthropic, anthropic-compatible, openai-compatible, moonshot, zhipu",
    )
    run_live_query.add_argument("--model", help="Optional model override.")
    run_live_query.add_argument("--api-key-env", help="Environment variable containing the API key.")
    run_live_query.add_argument("--base-url", help="Optional base URL override.")
    run_live_query.add_argument("--max-turns", type=int, default=8, help="Maximum provider turns.")
    run_live_query.add_argument(
        "--output-format",
        choices=["text", "json", "stream-json"],
        default="json",
        help="Output format for the live query result.",
    )

    suggest = subparsers.add_parser(
        "suggest-evolution",
        help="Build an evolution plan from a real saved harness session.",
    )
    suggest.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    suggest.add_argument("--capabilities", required=True, help="Path to a capabilities JSON file.")
    suggest.add_argument("--session-id", default="latest", help="Session ID to inspect.")
    suggest.add_argument("--ledger", help="Optional JSONL ledger path.")
    suggest.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    apply = subparsers.add_parser(
        "apply-evolution",
        help="Execute an evolution plan from a real saved session in candidate or apply mode.",
    )
    apply.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    apply.add_argument("--capabilities", required=True, help="Path to a capabilities JSON file.")
    apply.add_argument("--session-id", default="latest", help="Session ID to inspect.")
    apply.add_argument("--mode", choices=["candidate", "apply", "promote", "auto"], default="candidate", help="Execution mode.")
    apply.add_argument("--run-validation", action="store_true", help="Actually run regression validation commands.")
    apply.add_argument(
        "--allow-unvalidated-promotion",
        action="store_true",
        help="Allow promote mode to continue even when validation commands are only recorded, not executed.",
    )
    apply.add_argument("--ledger", help="Optional JSONL ledger path.")
    apply.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    executions = subparsers.add_parser("executions-list", help="List saved evolution execution records.")
    executions.add_argument("--workspace", required=True, help="Workspace root to inspect.")

    promotions = subparsers.add_parser("promotions-report", help="Summarize long-term promotion outcomes.")
    promotions.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    promotions.add_argument("--limit", type=int, default=50, help="Maximum records to analyze.")

    promotion_analytics = subparsers.add_parser("promotion-analytics", help="Show richer promotion analytics.")
    promotion_analytics.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    promotion_analytics.add_argument("--limit", type=int, default=100, help="Maximum records to analyze.")

    rollback = subparsers.add_parser("rollback-evolution", help="Rollback the last or specified execution record.")
    rollback.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    rollback.add_argument("--record", help="Optional execution record path.")
    rollback.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    sessions = subparsers.add_parser("sessions-list", help="List saved harness sessions.")
    sessions.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    sessions.add_argument("--limit", type=int, default=20, help="Maximum sessions to list.")

    sessions_report = subparsers.add_parser("sessions-report", help="Summarize archived session behavior.")
    sessions_report.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    sessions_report.add_argument("--limit", type=int, default=50, help="Maximum sessions to analyze.")

    session_show = subparsers.add_parser("session-show", help="Show one saved session.")
    session_show.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    session_show.add_argument("--id", default="latest", help="Session ID.")

    session_export = subparsers.add_parser("session-export", help="Export one saved session to markdown.")
    session_export.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    session_export.add_argument("--id", default="latest", help="Session ID.")

    benchmark_run = subparsers.add_parser("benchmark-run", help="Run a benchmark dataset against a provider configuration.")
    benchmark_run.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    benchmark_run.add_argument("--dataset", required=True, help="Benchmark dataset JSON path.")
    benchmark_run.add_argument("--settings", help="Optional settings.json path.")
    benchmark_run.add_argument("--provider-script", help="Optional scripted provider JSON path.")

    benchmark_compare = subparsers.add_parser("benchmark-compare", help="Compare two saved benchmark result files.")
    benchmark_compare.add_argument("--left", required=True, help="Left benchmark result path.")
    benchmark_compare.add_argument("--right", required=True, help="Right benchmark result path.")

    task_shell = subparsers.add_parser("task-shell", help="Start a background shell task.")
    task_shell.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    task_shell.add_argument("--shell-command", dest="shell_command", required=True, help="Shell command to execute.")
    task_shell.add_argument("--description", required=True, help="Short description for the task.")

    task_agent = subparsers.add_parser("task-agent", help="Start a background agent task.")
    task_agent.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    task_agent.add_argument("--name", required=True, help="Agent name.")
    task_agent.add_argument("--task", required=True, help="Task assigned to the agent.")
    task_agent.add_argument("--provider-script", required=True, help="Path to a scripted provider JSON file.")
    task_agent.add_argument("--description", help="Optional task description.")
    task_agent.add_argument("--max-turns", type=int, default=8, help="Maximum provider turns.")
    task_agent.add_argument("--settings", help="Optional settings.json path.")

    tasks_list = subparsers.add_parser("tasks-list", help="List background tasks.")
    tasks_list.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    tasks_list.add_argument("--status", help="Optional status filter.")

    task_get = subparsers.add_parser("task-get", help="Show one task record.")
    task_get.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    task_get.add_argument("--id", required=True, help="Task ID.")

    task_output = subparsers.add_parser("task-output", help="Read task output log.")
    task_output.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    task_output.add_argument("--id", required=True, help="Task ID.")
    task_output.add_argument("--max-bytes", type=int, default=12000, help="Tail length.")

    task_stop = subparsers.add_parser("task-stop", help="Stop a running task.")
    task_stop.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    task_stop.add_argument("--id", required=True, help="Task ID.")

    task_wait = subparsers.add_parser("task-wait", help="Wait for a task to reach a terminal state.")
    task_wait.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    task_wait.add_argument("--id", required=True, help="Task ID.")
    task_wait.add_argument("--timeout-s", type=float, default=30.0, help="Timeout in seconds.")

    tasks_prune = subparsers.add_parser("tasks-prune", help="Prune old task records and logs.")
    tasks_prune.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    tasks_prune.add_argument("--keep-last", type=int, default=50, help="How many recent tasks to keep.")

    skills = subparsers.add_parser("list-skills", help="List workspace and plugin skills.")
    skills.add_argument("--workspace", required=True, help="Workspace root to inspect.")

    hooks = subparsers.add_parser("list-hooks", help="List workspace hooks.")
    hooks.add_argument("--workspace", required=True, help="Workspace root to inspect.")

    memory_list = subparsers.add_parser("memory-list", help="List memory entries.")
    memory_list.add_argument("--workspace", required=True, help="Workspace root to inspect.")

    memory_add = subparsers.add_parser("memory-add", help="Add a persistent memory entry.")
    memory_add.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    memory_add.add_argument("--title", required=True, help="Memory title.")
    memory_add.add_argument("--content", required=True, help="Memory content.")

    memory_remove = subparsers.add_parser("memory-remove", help="Remove a persistent memory entry.")
    memory_remove.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    memory_remove.add_argument("--name", required=True, help="Memory file stem or name.")

    permission_check = subparsers.add_parser("permissions-check", help="Evaluate one tool action against settings.")
    permission_check.add_argument("--tool", required=True, help="Tool name.")
    permission_check.add_argument("--settings", help="Optional settings.json path.")
    permission_check.add_argument("--workspace", default=".", help="Workspace root used for context.")
    permission_check.add_argument("--read-only", action="store_true", help="Mark the action as read-only.")
    permission_check.add_argument("--file-path", help="Optional file path for path rule matching.")
    permission_check.add_argument("--shell-command", help="Optional shell command to evaluate.")

    plan = subparsers.add_parser("plan", help="Build an evolution plan from one trace.")
    plan.add_argument("--trace", required=True, help="Path to a task trace JSON file.")
    plan.add_argument("--capabilities", required=True, help="Path to a capabilities JSON file.")
    plan.add_argument("--workspace", required=True, help="Workspace root to inspect.")
    plan.add_argument("--ledger", help="Optional JSONL ledger path.")
    plan.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    inspect = subparsers.add_parser("inspect-workspace", help="Inspect a Claude/OpenHarness-style workspace.")
    inspect.add_argument("--workspace", required=True, help="Workspace root to inspect.")

    demo = subparsers.add_parser("demo", help="Run the bundled demo.")
    demo.add_argument(
        "--root",
        default=Path(__file__).resolve().parents[2],
        help="Project root used to resolve bundled examples.",
    )

    return parser


def main() -> None:
    enable_utf8_console()
    parser = build_parser()
    args = parser.parse_args()

    if args.backend_only:
        raise SystemExit(
            run_backend_host(
                workspace=args.workspace or ".",
                settings_path=args.settings,
                provider_script=args.provider_script,
                resume=args.resume,
            )
        )

    if args.command is None:
        workspace = args.workspace or "."
        if args.prompt:
            runtime = HarnessRuntime(workspace, settings_path=args.settings)
            _configure_console_approvals(runtime)
            engine = ConversationEngine(runtime)
            if args.resume and args.resume.lower() != "none":
                engine.load_session(args.resume)
            provider = (
                ScriptedProvider.from_file(args.provider_script)
                if args.provider_script
                else build_live_provider(settings=runtime.settings)
            )
            if args.output_format == "text":
                _print_query_text_stream(engine, prompt=args.prompt, provider=provider)
            elif args.output_format == "stream-json":
                _print_query_stream_json(engine, prompt=args.prompt, provider=provider)
            else:
                result = engine.submit(
                    prompt=args.prompt,
                    provider=provider,
                )
                print(json.dumps(_query_result_payload(result), indent=2, ensure_ascii=False))
            return
        if not args.text_ui:
            try:
                raise SystemExit(
                    asyncio.run(
                        launch_react_tui(
                            workspace=str(Path(workspace).resolve()),
                            settings_path=args.settings,
                            provider_script=args.provider_script,
                            resume=args.resume,
                        )
                    )
                )
            except KeyboardInterrupt:
                return
            except RuntimeError:
                pass
            except FileNotFoundError:
                pass
        run_interactive_repl(
            workspace,
            settings_path=args.settings,
            provider_script=args.provider_script,
            resume=args.resume,
        )
        return

    if args.command == "status":
        settings = load_settings(args.settings, workspace=args.workspace)
        from evo_harness.core.workspace import discover_workspace

        workspace = discover_workspace(args.workspace)
        env = get_environment_info(args.workspace)
        skills = load_workspace_skills(args.workspace, settings=settings)
        hooks = load_workspace_hooks(args.workspace, settings=settings)
        commands = load_workspace_commands(args.workspace, settings=settings)
        agents = load_workspace_agents(args.workspace, settings=settings)
        plugins = load_workspace_plugins(args.workspace, settings=settings)
        marketplaces = load_marketplaces(args.workspace, settings)
        memories = list_memory_entries(args.workspace)
        runtime = HarnessRuntime(args.workspace, settings_path=args.settings)
        tasks = get_task_manager(args.workspace).list_tasks()
        payload = {
            "workspace": workspace.to_dict(),
            "environment": env.to_dict(),
            "settings": settings.to_dict(),
            "provider": _provider_report(settings),
            "skill_count": len(skills),
            "hook_count": len(hooks),
            "command_count": len(commands),
            "agent_count": len(agents),
            "plugin_count": len(plugins),
            "marketplace_count": len(marketplaces),
            "tool_count": len(runtime.list_tools()),
            "mcp_server_count": len(runtime.list_mcp_servers()),
            "mcp_tool_count": len(runtime.list_mcp_tools()),
            "mcp_resource_count": len(runtime.list_mcp_resources()),
            "mcp_prompt_count": len(runtime.list_mcp_prompts()),
            "memory_entry_count": len(memories),
            "pending_approval_count": len(runtime.list_approvals(status="pending")),
            "task_count": len(tasks),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "build-prompt":
        settings = load_settings(args.settings, workspace=args.workspace)
        prompt = build_system_prompt(args.workspace, custom_prompt=settings.system_prompt, settings=settings)
        print(prompt)
        return

    if args.command == "settings-show":
        payload = load_settings(args.settings, workspace=args.workspace).to_dict()
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "init":
        result = initialize_workspace(
            args.workspace,
            provider_profile=args.provider_profile,
            model=args.model,
            api_key_env=args.api_key_env,
            base_url=args.base_url,
            force=args.force,
        )
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return

    if args.command == "providers-list":
        print(json.dumps(list_provider_profiles(), indent=2, ensure_ascii=False))
        return

    if args.command == "provider-detect":
        settings = load_settings(args.settings, workspace=args.workspace)
        payload = _provider_report(settings)
        payload["detected"] = detect_provider_profile(
            provider=settings.provider.provider,
            profile=settings.provider.profile,
            base_url=args.base_url or settings.provider.base_url,
            model=args.model or settings.model,
        ).to_dict()
        if args.model:
            payload["model"] = args.model
        if args.base_url:
            payload["base_url"] = args.base_url
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "provider-template":
        profile = detect_provider_profile(profile=args.profile)
        payload = {
            "model": args.model or "",
            "provider": {
                "provider": profile.name,
                "profile": profile.name,
                "api_format": profile.api_format,
                "api_key_env": profile.default_api_key_env,
                "base_url": profile.default_base_url,
                "auth_scheme": profile.auth_scheme,
            },
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "tools-list":
        runtime = HarnessRuntime(args.workspace, settings_path=args.settings)
        print(json.dumps(runtime.list_tools(), indent=2, ensure_ascii=False))
        return

    if args.command == "doctor":
        payload = _build_doctor_report(args.workspace, settings_path=args.settings)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "approvals-list":
        runtime = HarnessRuntime(args.workspace, settings_path=args.settings)
        print(json.dumps(runtime.list_approvals(status=args.status), indent=2, ensure_ascii=False))
        return

    if args.command == "approval-decide":
        runtime = HarnessRuntime(args.workspace, settings_path=args.settings)
        payload = runtime.approval_manager.decide(
            args.id,
            approved=args.decision == "approve",
            note=args.note,
        ).to_dict()
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "mcp-list":
        settings = load_settings(args.settings, workspace=args.workspace)
        if args.kind == "servers":
            payload = list_mcp_servers(args.workspace, settings=settings)
        elif args.kind == "tools":
            payload = list_mcp_tools(args.workspace, settings=settings)
        elif args.kind == "resources":
            payload = list_mcp_resources(args.workspace, settings=settings)
        elif args.kind == "prompts":
            payload = list_mcp_prompts(args.workspace, settings=settings)
        else:
            payload = {
                "servers": list_mcp_servers(args.workspace, settings=settings),
                "tools": list_mcp_tools(args.workspace, settings=settings),
                "resources": list_mcp_resources(args.workspace, settings=settings),
                "prompts": list_mcp_prompts(args.workspace, settings=settings),
            }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "mcp-call":
        from evo_harness.harness import call_mcp_method

        payload = call_mcp_method(
            args.workspace,
            server_name=args.server,
            method=args.method,
            params=_load_jsonish_arg(args.params),
        ).to_dict()
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "tool-run":
        runtime = HarnessRuntime(args.workspace, settings_path=args.settings)
        if bool(args.input) == bool(args.input_file):
            raise SystemExit("Pass exactly one of --input or --input-file")
        tool_input = _load_jsonish_arg("@" + args.input_file) if args.input_file else _load_jsonish_arg(args.input)
        result = runtime.execute_tool(args.tool, tool_input)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return

    if args.command == "chat":
        if not args.text_ui:
            try:
                raise SystemExit(
                    asyncio.run(
                        launch_react_tui(
                            workspace=str(Path(args.workspace).resolve()),
                            settings_path=args.settings,
                            provider_script=args.provider_script,
                            resume=args.resume,
                        )
                    )
                )
            except RuntimeError:
                pass
            except FileNotFoundError:
                pass
        run_interactive_repl(
            args.workspace,
            settings_path=args.settings,
            provider_script=args.provider_script,
            resume=args.resume,
        )
        return

    if args.command == "ui":
        if not args.text_ui:
            raise SystemExit(
                asyncio.run(
                    launch_react_tui(
                        workspace=str(Path(args.workspace).resolve()),
                        settings_path=args.settings,
                        provider_script=args.provider_script,
                        resume=args.resume,
                    )
                )
            )
        run_home_ui(args.workspace, settings_path=args.settings, provider_script=args.provider_script)
        return

    if args.command == "commands-list":
        settings = load_settings(workspace=args.workspace)
        payload = [command.to_dict() for command in load_workspace_commands(args.workspace, settings=settings)]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "command-show":
        command = find_command(args.workspace, args.name)
        if command is None:
            raise SystemExit(f"Command not found: {args.name}")
        print(json.dumps(command.to_dict(), indent=2, ensure_ascii=False))
        return

    if args.command == "plugins-list":
        settings = load_settings(workspace=args.workspace)
        payload = [plugin.to_dict() for plugin in load_workspace_plugins(args.workspace, settings=settings)]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "marketplaces-list":
        settings = load_settings(args.settings, workspace=args.workspace)
        payload = [marketplace.to_dict() for marketplace in load_marketplaces(args.workspace, settings)]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "marketplace-plugins":
        settings = load_settings(args.settings, workspace=args.workspace)
        payload = []
        for marketplace in load_marketplaces(args.workspace, settings):
            payload.append(
                {
                    "marketplace": marketplace.name,
                    "plugins": [plugin.to_dict() for plugin in marketplace.plugins],
                }
            )
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "marketplace-install":
        settings = load_settings(args.settings, workspace=args.workspace)
        path = install_marketplace_plugin(
            args.workspace,
            marketplace_name=args.marketplace,
            plugin_name=args.plugin,
            settings=settings,
        )
        print(str(path))
        return

    if args.command == "plugin-enable":
        settings = load_settings(workspace=args.workspace)
        settings.enabled_plugins[args.name] = True
        path = Path(args.workspace).resolve() / ".evo-harness" / "settings.json"
        save_settings(settings, path)
        print(str(path))
        return

    if args.command == "plugin-disable":
        settings = load_settings(workspace=args.workspace)
        settings.enabled_plugins[args.name] = False
        path = Path(args.workspace).resolve() / ".evo-harness" / "settings.json"
        save_settings(settings, path)
        print(str(path))
        return

    if args.command == "agents-list":
        settings = load_settings(workspace=args.workspace)
        payload = [agent.to_dict() for agent in load_workspace_agents(args.workspace, settings=settings)]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "agent-show":
        agent = find_agent(args.workspace, args.name)
        if agent is None:
            raise SystemExit(f"Agent not found: {args.name}")
        print(json.dumps(agent.to_dict(), indent=2, ensure_ascii=False))
        return

    if args.command == "run-agent":
        runtime = HarnessRuntime(args.workspace, settings_path=args.settings)
        agent = find_agent(args.workspace, args.name)
        if agent is None:
            raise SystemExit(f"Agent not found: {args.name}")
        provider = ScriptedProvider.from_file(args.provider_script)
        result = run_subagent(
            runtime,
            agent=agent,
            task=args.task,
            provider=provider,
            max_turns=args.max_turns,
        )
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return

    if args.command == "run-workflow":
        runtime = HarnessRuntime(args.workspace, settings_path=args.settings)
        workflow = load_workflow(args.workflow)
        provider_script = str(Path(args.provider_script).resolve())
        result = run_workflow(
            runtime,
            workflow=workflow,
            provider_factory=lambda: ScriptedProvider.from_file(provider_script),
            max_turns=args.max_turns,
        )
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return

    if args.command == "command-render":
        runtime = HarnessRuntime(args.workspace)
        print(runtime.render_command(args.name, args.arguments))
        return

    if args.command == "run-script":
        runtime = HarnessRuntime(args.workspace, settings_path=args.settings)
        payload = runtime.run_script(args.script)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "run-query":
        runtime = HarnessRuntime(args.workspace, settings_path=args.settings)
        if args.output_format == "text":
            _configure_console_approvals(runtime)
        provider = ScriptedProvider.from_file(args.provider_script)
        engine = ConversationEngine(runtime)
        if args.output_format == "text":
            _print_query_text_stream(
                engine,
                prompt=args.prompt,
                provider=provider,
                command_name=args.query_command_name,
                command_arguments=args.query_command_arguments,
                max_turns=args.max_turns,
            )
        elif args.output_format == "stream-json":
            _print_query_stream_json(
                engine,
                prompt=args.prompt,
                provider=provider,
                command_name=args.query_command_name,
                command_arguments=args.query_command_arguments,
                max_turns=args.max_turns,
            )
        else:
            result = engine.submit(
                prompt=args.prompt,
                provider=provider,
                command_name=args.query_command_name,
                command_arguments=args.query_command_arguments,
                max_turns=args.max_turns,
            )
            print(json.dumps(_query_result_payload(result), indent=2, ensure_ascii=False))
        return

    if args.command == "run-live-query":
        runtime = HarnessRuntime(args.workspace, settings_path=args.settings)
        if args.output_format == "text":
            _configure_console_approvals(runtime)
        provider = build_live_provider(
            settings=runtime.settings,
            model_override=args.model,
            provider_override=args.provider,
            base_url_override=args.base_url,
            api_key_env_override=args.api_key_env,
        )
        engine = ConversationEngine(runtime)
        if args.output_format == "text":
            _print_query_text_stream(
                engine,
                prompt=args.prompt,
                provider=provider,
                command_name=args.live_command_name,
                command_arguments=args.live_command_arguments,
                max_turns=args.max_turns,
            )
        elif args.output_format == "stream-json":
            _print_query_stream_json(
                engine,
                prompt=args.prompt,
                provider=provider,
                command_name=args.live_command_name,
                command_arguments=args.live_command_arguments,
                max_turns=args.max_turns,
            )
        else:
            result = engine.submit(
                prompt=args.prompt,
                provider=provider,
                command_name=args.live_command_name,
                command_arguments=args.live_command_arguments,
                max_turns=args.max_turns,
            )
            print(json.dumps(_query_result_payload(result), indent=2, ensure_ascii=False))
        return

    if args.command == "suggest-evolution":
        capabilities = _load_capabilities(args.capabilities)
        plan = plan_from_saved_session(
            args.workspace,
            capabilities=capabilities,
            session_id=args.session_id,
        )
        if getattr(args, "ledger", None):
            EvolutionLedger(Path(args.ledger)).append(plan)
        payload = plan.to_dict()
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            _print_human(payload)
        return

    if args.command == "apply-evolution":
        capabilities = _load_capabilities(args.capabilities)
        plan = plan_from_saved_session(
            args.workspace,
            capabilities=capabilities,
            session_id=args.session_id,
        )
        execution = ControlledEvolutionExecutor().execute(
            plan,
            workspace_root=args.workspace,
            mode=args.mode,
            run_validation=args.run_validation,
            allow_unvalidated_promotion=args.allow_unvalidated_promotion,
        )
        record_path = write_execution_record(
            args.workspace,
            plan=plan,
            execution=execution,
        )
        if getattr(args, "ledger", None):
            EvolutionLedger(Path(args.ledger)).append(
                plan,
                status=f"executed:{args.mode}:{'ok' if execution.success else 'failed'}",
            )
        payload = {
            "plan": plan.to_dict(),
            "execution": execution.to_dict(),
            "record_path": str(record_path),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "executions-list":
        payload = [str(path) for path in list_execution_records(args.workspace)]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "promotions-report":
        payload = promotion_report(args.workspace, limit=args.limit)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "promotion-analytics":
        payload = promotion_analytics_report(args.workspace, limit=args.limit)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "rollback-evolution":
        result = rollback_execution(args.workspace, record_path=args.record)
        payload = result.to_dict()
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "sessions-list":
        payload = list_session_snapshots(args.workspace, limit=args.limit)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "sessions-report":
        payload = session_analytics_report(args.workspace, limit=args.limit)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "session-show":
        payload = load_session_snapshot(args.workspace, session_id=args.id)
        if payload is None:
            raise SystemExit(f"Session not found: {args.id}")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "session-export":
        path = export_session_markdown(args.workspace, session_id=args.id)
        print(str(path))
        return

    if args.command == "benchmark-run":
        provider_factory, provider_label = build_provider_factory(
            workspace=args.workspace,
            settings_path=args.settings,
            provider_script=args.provider_script,
        )
        run = run_benchmark(
            args.workspace,
            dataset_path=args.dataset,
            provider_factory=provider_factory,
            settings_path=args.settings,
            provider_label=provider_label,
        )
        path = write_benchmark_run(args.workspace, run)
        print(json.dumps({"run": run.to_dict(), "path": str(path)}, indent=2, ensure_ascii=False))
        return

    if args.command == "benchmark-compare":
        payload = compare_benchmark_runs(args.left, args.right)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "task-shell":
        manager = get_task_manager(args.workspace)
        record = manager.create_shell_task(
            command=args.shell_command,
            description=args.description,
        )
        print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
        return

    if args.command == "task-agent":
        manager = get_task_manager(args.workspace)
        record = manager.create_agent_task(
            agent_name=args.name,
            task=args.task,
            provider_script=args.provider_script,
            description=args.description,
            max_turns=args.max_turns,
            settings_path=args.settings,
        )
        print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
        return

    if args.command == "tasks-list":
        manager = get_task_manager(args.workspace)
        payload = [record.to_dict() for record in manager.list_tasks(status=args.status)]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "task-get":
        manager = get_task_manager(args.workspace)
        record = manager.get_task(args.id)
        if record is None:
            raise SystemExit(f"Task not found: {args.id}")
        print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
        return

    if args.command == "task-output":
        manager = get_task_manager(args.workspace)
        print(manager.read_task_output(args.id, max_bytes=args.max_bytes))
        return

    if args.command == "task-stop":
        manager = get_task_manager(args.workspace)
        record = manager.stop_task(args.id)
        print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
        return

    if args.command == "task-wait":
        manager = get_task_manager(args.workspace)
        record = manager.wait_task(args.id, timeout_s=args.timeout_s)
        print(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
        return

    if args.command == "tasks-prune":
        manager = get_task_manager(args.workspace)
        removed = manager.prune_tasks(keep_last=args.keep_last)
        print(json.dumps({"removed": removed}, indent=2, ensure_ascii=False))
        return

    if args.command == "list-skills":
        settings = load_settings(workspace=args.workspace)
        payload = [skill.to_dict() for skill in load_workspace_skills(args.workspace, settings=settings)]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "list-hooks":
        settings = load_settings(workspace=args.workspace)
        payload = [hook.to_dict() for hook in load_workspace_hooks(args.workspace, settings=settings)]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "memory-list":
        payload = [str(path) for path in list_memory_entries(args.workspace)]
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    if args.command == "memory-add":
        path = add_memory_entry(args.workspace, args.title, args.content)
        print(str(path))
        return

    if args.command == "memory-remove":
        removed = remove_memory_entry(args.workspace, args.name)
        print(json.dumps({"removed": removed}, ensure_ascii=False))
        return

    if args.command == "permissions-check":
        settings = load_settings(args.settings, workspace=args.workspace)
        decision = PermissionChecker(settings.permission).evaluate(
            args.tool,
            is_read_only=args.read_only,
            file_path=args.file_path,
            command=args.shell_command,
        )
        print(
            json.dumps(
                {
                    "allowed": decision.allowed,
                    "requires_confirmation": decision.requires_confirmation,
                    "reason": decision.reason,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    if args.command == "inspect-workspace":
        from evo_harness.core.workspace import discover_workspace

        snapshot = discover_workspace(args.workspace)
        print(json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False))
        return

    if args.command == "demo":
        root = Path(args.root)
        args.trace = root / "examples" / "coding_trace.json"
        args.capabilities = root / "examples" / "openharness_capabilities.json"
        args.workspace = root / "examples" / "workspace"
        args.ledger = root / ".evo-harness" / "ledger.jsonl"
        args.json = False

    engine = EvolutionEngine()
    trace = TaskTrace.from_dict(_load_json(args.trace))
    capabilities = _load_capabilities(args.capabilities)
    plan = engine.plan(
        trace=trace,
        capabilities=capabilities,
        workspace_root=args.workspace,
    )

    if getattr(args, "ledger", None):
        EvolutionLedger(Path(args.ledger)).append(plan)

    payload = plan.to_dict()
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        _print_human(payload)
