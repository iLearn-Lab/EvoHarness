from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evo_harness.harness.agents import load_workspace_agents
from evo_harness.harness.commands import load_workspace_commands
from evo_harness.harness.marketplaces import load_marketplaces
from evo_harness.harness.plugins import load_workspace_plugins
from evo_harness.harness.provider import detect_provider_profile
from evo_harness.harness.runtime import HarnessRuntime
from evo_harness.harness.session import list_session_snapshots, session_analytics_report
from evo_harness.harness.slash_commands import (
    SlashCommandContext,
    create_default_slash_command_registry,
    format_prompt_label,
    format_session_banner,
)
from evo_harness.harness.skills import load_workspace_skills
from evo_harness.harness.tasks import get_task_manager


@dataclass
class HomeState:
    workspace: str
    model: str
    provider_profile: str
    permission_mode: str
    query_max_turns: int
    query_max_tool_calls: int
    max_mutating_tools: int
    tool_count: int
    command_count: int
    agent_count: int
    plugin_count: int
    marketplace_count: int
    skill_count: int
    session_count: int
    task_count: int
    mcp_server_count: int
    mcp_tool_count: int
    mcp_resource_count: int
    mcp_prompt_count: int
    pending_approvals: int
    promotion_totals: dict[str, Any]
    promotion_analytics: dict[str, Any]
    session_totals: dict[str, Any]
    recent_sessions: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def build_home_state(workspace: str | Path, *, settings_path: str | Path | None = None) -> HomeState:
    from evo_harness.execution import promotion_analytics_report, promotion_report

    runtime = HarnessRuntime(workspace, settings_path=settings_path)
    settings = runtime.settings
    session_report = session_analytics_report(workspace, limit=20)
    warnings: list[str] = []
    if not runtime.list_mcp_servers():
        warnings.append("No MCP registry sources loaded.")
    if settings.permission.mode == "default":
        warnings.append("Mutating tools still require confirmation in default mode.")
    if session_report["totals"]["sessions"] < 3:
        warnings.append("Session history is still sparse for deeper evolution analytics.")

    return HomeState(
        workspace=str(Path(workspace).resolve()),
        model=settings.model,
        provider_profile=detect_provider_profile(
            provider=settings.provider.provider,
            profile=settings.provider.profile,
            base_url=settings.provider.base_url,
            model=settings.model,
        ).name,
        permission_mode=settings.permission.mode,
        query_max_turns=settings.query.max_turns,
        query_max_tool_calls=settings.query.max_total_tool_calls,
        max_mutating_tools=settings.safety.max_mutating_tools_per_query,
        tool_count=len(runtime.list_tools()),
        command_count=len(load_workspace_commands(workspace, settings=settings)),
        agent_count=len(load_workspace_agents(workspace, settings=settings)),
        plugin_count=len(load_workspace_plugins(workspace, settings=settings)),
        marketplace_count=len(load_marketplaces(workspace, settings)),
        skill_count=len(load_workspace_skills(workspace, settings=settings)),
        session_count=len(list_session_snapshots(workspace)),
        task_count=len(get_task_manager(workspace).list_tasks()),
        mcp_server_count=len(runtime.list_mcp_servers()),
        mcp_tool_count=len(runtime.list_mcp_tools()),
        mcp_resource_count=len(runtime.list_mcp_resources()),
        mcp_prompt_count=len(runtime.list_mcp_prompts()),
        pending_approvals=len(runtime.list_approvals(status="pending")),
        promotion_totals=promotion_report(workspace)["totals"],
        promotion_analytics=promotion_analytics_report(workspace, limit=30)["totals"],
        session_totals=session_report["totals"],
        recent_sessions=session_report["recent"][:5],
        warnings=warnings,
    )


def render_home(state: HomeState) -> str:
    lines = [
        "=" * 88,
        "Evo Harness Dashboard",
        "=" * 88,
        f"Workspace    : {state.workspace}",
        f"Model        : {state.model}",
        f"Provider     : {state.provider_profile}",
        f"Permissions  : {state.permission_mode}",
        "",
        "Runtime",
        f"  tools={state.tool_count} commands={state.command_count} agents={state.agent_count} skills={state.skill_count}",
        f"  plugins={state.plugin_count} marketplaces={state.marketplace_count}",
        f"  mcp_servers={state.mcp_server_count} mcp_tools={state.mcp_tool_count} mcp_resources={state.mcp_resource_count} mcp_prompts={state.mcp_prompt_count}",
        f"  query_max_turns={state.query_max_turns} query_max_tool_calls={state.query_max_tool_calls} safety_max_mutating_tools={state.max_mutating_tools}",
        "",
        "Sessions",
        f"  sessions={state.session_count} tasks={state.task_count} pending_approvals={state.pending_approvals} avg_turns={state.session_totals.get('avg_turns', 0)} avg_tool_calls={state.session_totals.get('avg_tool_calls', 0)}",
        "",
        "Promotion",
        "  " + " ".join(f"{key}={value}" for key, value in state.promotion_totals.items()),
        f"  analytics_avg_score={state.promotion_analytics.get('avg_score')} records={state.promotion_analytics.get('records')}",
    ]
    if state.recent_sessions:
        lines.extend(["", "Recent Sessions"])
        for item in state.recent_sessions:
            lines.append(
                f"  {item.get('session_id')} stop={item.get('stop_reason')} turns={item.get('turn_count')} tools={item.get('tool_calls')} command={item.get('active_command') or '-'}"
            )
    if state.warnings:
        lines.extend(["", "Warnings"])
        for warning in state.warnings:
            lines.append(f"  - {warning}")
    lines.extend(
        [
            "",
            "Commands",
            "  refresh         redraw the dashboard",
            "  chat            enter chat mode",
            "  prompt <text>   run one prompt immediately",
            "  resume <id>     restore one saved session",
            "  commands        list commands",
            "  agents          list agents",
            "  plugins         list plugins",
            "  approvals       list pending approvals",
            "  mcp            show MCP registry",
            "  analytics       show session analytics",
            "  doctor          show doctor report",
            "  tasks           list tasks",
            "  sessions        list sessions",
            "  promotions      show promotion report",
            "  quit            exit",
            "=" * 88,
        ]
    )
    return "\n".join(lines)


def run_home_ui(
    workspace: str | Path,
    *,
    settings_path: str | Path | None = None,
    provider_script: str | Path | None = None,
) -> None:
    from evo_harness.execution import promotion_report
    from evo_harness.harness.conversation import ConversationEngine

    runtime = HarnessRuntime(workspace, settings_path=settings_path)
    runtime.approval_prompt = _prompt_for_approval
    engine = ConversationEngine(runtime)
    provider = _build_provider(runtime, provider_script=provider_script)

    while True:
        _clear_screen()
        print(render_home(build_home_state(workspace, settings_path=settings_path)))
        raw = input("home> ").strip()
        if not raw:
            continue
        if raw == "quit":
            return
        if raw == "refresh":
            continue
        if raw == "commands":
            _show_json([item.to_dict() for item in load_workspace_commands(workspace, settings=runtime.settings)])
            continue
        if raw == "agents":
            _show_json([item.to_dict() for item in load_workspace_agents(workspace, settings=runtime.settings)])
            continue
        if raw == "plugins":
            _show_json([item.to_dict() for item in load_workspace_plugins(workspace, settings=runtime.settings)])
            continue
        if raw == "approvals":
            _show_json(runtime.list_approvals(status="pending"))
            continue
        if raw == "mcp":
            _show_json(
                {
                    "servers": runtime.list_mcp_servers(),
                    "tools": runtime.list_mcp_tools(),
                    "resources": runtime.list_mcp_resources(),
                    "prompts": runtime.list_mcp_prompts(),
                }
            )
            continue
        if raw == "analytics":
            _show_json(session_analytics_report(workspace))
            continue
        if raw == "doctor":
            from evo_harness.cli import _build_doctor_report

            _show_json(_build_doctor_report(workspace, settings_path=settings_path))
            continue
        if raw == "tasks":
            _show_json([item.to_dict() for item in get_task_manager(workspace).list_tasks()])
            continue
        if raw == "sessions":
            _show_json(list_session_snapshots(workspace))
            continue
        if raw == "promotions":
            _show_json(promotion_report(workspace))
            continue
        if raw == "chat":
            run_interactive_repl(
                workspace,
                settings_path=settings_path,
                provider_script=provider_script,
                runtime=runtime,
                engine=engine,
                provider=provider,
            )
            continue
        if raw.startswith("prompt "):
            _run_single_prompt(engine, provider, raw[len("prompt ") :].strip())
            continue
        if raw.startswith("resume "):
            session_id = raw[len("resume ") :].strip() or "latest"
            if engine.load_session(session_id):
                _show_text(f"Resumed session {session_id}.")
            else:
                _show_text(f"Session not found: {session_id}")
            continue
        _show_text(f"Unknown command: {raw}")


def _run_chat_loop(engine, provider) -> None:
    print("Chat mode. Use /exit to return home, /clear to clear history.")
    while True:
        prompt = input("> ").strip()
        if not prompt:
            continue
        if prompt == "/exit":
            return
        if prompt == "/clear":
            engine.clear()
            print("Conversation cleared.")
            continue
        _stream_prompt(engine, provider, prompt, pause=False)


def run_interactive_repl(
    workspace: str | Path,
    *,
    settings_path: str | Path | None = None,
    provider_script: str | Path | None = None,
    runtime: HarnessRuntime | None = None,
    engine=None,
    provider=None,
    resume: str | None = None,
) -> None:
    from evo_harness.harness.conversation import ConversationEngine
    from evo_harness.harness.provider import ScriptedProvider, build_live_provider

    runtime = runtime or HarnessRuntime(workspace, settings_path=settings_path)
    runtime.approval_prompt = _prompt_for_approval
    engine = engine or ConversationEngine(runtime)
    if resume and resume.lower() != "none":
        engine.load_session(resume)

    registry = create_default_slash_command_registry()
    print(format_session_banner(runtime))
    if not any(
        candidate.exists()
        for candidate in (
            Path(workspace).resolve() / "CLAUDE.md",
            Path(workspace).resolve() / ".evo-harness" / "settings.json",
        )
    ):
        print("Workspace is not initialized yet. Run /init to scaffold project files.")

    scripted_provider = provider
    if provider_script and scripted_provider is None:
        scripted_provider = ScriptedProvider.from_file(provider_script)

    while True:
        raw = input(format_prompt_label(runtime)).strip()
        if not raw:
            continue
        if raw.startswith("/"):
            result = registry.dispatch(
                raw,
                SlashCommandContext(runtime=runtime, engine=engine, prompt_fn=input),
            )
            if result is None:
                print(f"Unknown command: {raw}. Use /help.")
                continue
            if result.clear_screen:
                _clear_screen()
                print(format_session_banner(runtime))
            if result.message:
                print(result.message)
            if result.should_exit:
                return
            continue
        try:
            active_provider = scripted_provider or build_live_provider(settings=runtime.settings)
        except Exception as exc:
            print(f"Provider setup failed: {exc}")
            print("Use /setup for guided configuration, or /login to save an API key.")
            continue
        _stream_prompt(engine, active_provider, raw, pause=False)


def _run_single_prompt(engine, provider, prompt: str) -> None:
    _stream_prompt(engine, provider, prompt, pause=True)


def _stream_prompt(engine, provider, prompt: str, *, pause: bool) -> None:
    saw_text = False
    try:
        for event in engine.submit_stream(prompt=prompt, provider=provider):
            name = event.__class__.__name__
            if name == "AssistantTextDelta":
                print(event.text, end="", flush=True)
                saw_text = True
            elif name == "AssistantTurnComplete" and saw_text:
                print()
    except Exception as exc:
        print(f"Request failed: {exc}")
    if saw_text:
        print()
    if pause:
        input("Press Enter to continue...")


def _build_provider(runtime: HarnessRuntime, *, provider_script: str | Path | None):
    from evo_harness.harness.provider import ScriptedProvider, build_live_provider

    if provider_script:
        return ScriptedProvider.from_file(provider_script)
    return build_live_provider(settings=runtime.settings)


def _show_json(payload: Any) -> None:
    print()
    import json

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    input("\nPress Enter to continue...")


def _show_text(text: str) -> None:
    print()
    print(text)
    input("\nPress Enter to continue...")


def _prompt_for_approval(request) -> bool:
    print()
    print(f"Approval required for `{request.tool_name}`")
    print(request.reason or "Mutating action requires approval.")
    if request.file_path:
        print(f"Path: {request.file_path}")
    if request.command:
        print(f"Command: {request.command}")
    response = input("Approve? [y/N]: ").strip().lower()
    return response in {"y", "yes"}


def _clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")
