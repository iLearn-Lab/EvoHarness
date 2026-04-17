from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from evo_harness.execution import (
    ControlledEvolutionExecutor,
    promotion_report,
    rollback_execution,
    write_execution_record,
)
from evo_harness.autonomous_evolution import assess_saved_session, run_autonomous_self_evolution
from evo_harness.harness.approvals import ApprovalManager
from evo_harness.harness.commands import load_workspace_commands
from evo_harness.harness.conversation import ConversationEngine
from evo_harness.harness.evolution_bridge import plan_from_saved_session
from evo_harness.harness.hooks import HookExecutor, load_workspace_hooks
from evo_harness.harness.marketplaces import install_marketplace_plugin, load_marketplaces
from evo_harness.harness.memory import (
    add_memory_entry,
    list_memory_entries,
    remove_memory_entry,
)
from evo_harness.harness.permissions import PermissionChecker, normalize_permission_mode
from evo_harness.harness.plugins import discover_plugin_paths, load_workspace_plugins
from evo_harness.harness.provider import PROVIDER_PROFILES, build_live_provider, detect_provider_profile
from evo_harness.harness.runtime import HarnessRuntime
from evo_harness.harness.session import list_session_snapshots, session_analytics_report
from evo_harness.harness.settings import load_settings, save_settings
from evo_harness.harness.skills import load_workspace_skills
from evo_harness.harness.subagents import run_subagent
from evo_harness.harness.tasks import get_task_manager


@dataclass(slots=True)
class SlashCommandResult:
    message: str | None = None
    should_exit: bool = False
    clear_screen: bool = False


@dataclass(slots=True)
class SlashCommandContext:
    runtime: HarnessRuntime
    engine: ConversationEngine
    prompt_fn: Callable[[str], str] = input


CommandHandler = Callable[[str, SlashCommandContext], SlashCommandResult]


@dataclass(slots=True)
class SlashCommand:
    name: str
    description: str
    handler: CommandHandler
    hidden: bool = False


class SlashCommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}

    def register(self, command: SlashCommand) -> None:
        self._commands[command.name] = command

    def dispatch(self, raw_input: str, context: SlashCommandContext) -> SlashCommandResult | None:
        if not raw_input.startswith("/"):
            return None
        name, _, args = raw_input[1:].partition(" ")
        command = self._commands.get(name.strip())
        if command is not None:
            return command.handler(args.strip(), context)
        return _dispatch_workspace_command(name.strip(), args.strip(), context)

    def help_text(self) -> str:
        lines = ["Available commands:"]
        for command in sorted(self._commands.values(), key=lambda item: item.name):
            if command.hidden:
                continue
            lines.append(f"/{command.name:<12} {command.description}")
        lines.append("/<workspace-command> activate a markdown workspace command, e.g. /inspect-repo auth flow")
        return "\n".join(lines)

    def visible_names(self) -> list[str]:
        return sorted(command.name for command in self._commands.values() if not command.hidden)


def create_default_slash_command_registry() -> SlashCommandRegistry:
    registry = SlashCommandRegistry()

    def _help_handler(_: str, context: SlashCommandContext) -> SlashCommandResult:
        del context
        return SlashCommandResult(message=registry.help_text())

    def _exit_handler(_: str, context: SlashCommandContext) -> SlashCommandResult:
        del context
        return SlashCommandResult(should_exit=True)

    def _clear_handler(_: str, context: SlashCommandContext) -> SlashCommandResult:
        context.engine.clear()
        return SlashCommandResult(message="Conversation cleared.", clear_screen=True)

    def _status_handler(_: str, context: SlashCommandContext) -> SlashCommandResult:
        runtime = context.runtime
        settings = runtime.settings
        active_command = runtime.active_command.name if runtime.active_command is not None else "(none)"
        session_count = len(list_session_snapshots(runtime.workspace, limit=20))
        profile = detect_provider_profile(
            provider=settings.provider.provider,
            profile=settings.provider.profile,
            base_url=settings.provider.base_url,
            model=settings.model,
        )
        return SlashCommandResult(
            message=(
                f"Workspace: {runtime.workspace}\n"
                f"Model: {settings.model}\n"
                f"Provider: {profile.name}\n"
                f"Permission mode: {settings.permission.mode}\n"
                f"Active command: {active_command}\n"
                f"Messages: {len(runtime.messages)}\n"
                f"Sessions: {session_count}"
            )
        )

    def _model_handler(args: str, context: SlashCommandContext) -> SlashCommandResult:
        runtime = context.runtime
        if not args:
            return SlashCommandResult(message=f"Model: {runtime.settings.model}")
        runtime.settings.model = args.strip()
        _save_runtime_settings(runtime)
        return SlashCommandResult(message=f"Updated model to {runtime.settings.model}")

    def _provider_handler(args: str, context: SlashCommandContext) -> SlashCommandResult:
        runtime = context.runtime
        if not args:
            profile = detect_provider_profile(
                provider=runtime.settings.provider.provider,
                profile=runtime.settings.provider.profile,
                base_url=runtime.settings.provider.base_url,
                model=runtime.settings.model,
            )
            return SlashCommandResult(
                message=(
                    f"Provider: {profile.name}\n"
                    f"API format: {runtime.settings.provider.api_format}\n"
                    f"Base URL: {runtime.settings.provider.base_url}\n"
                    f"API key env: {runtime.settings.provider.api_key_env}\n"
                    f"API key saved: {'yes' if bool(runtime.settings.provider.api_key) else 'no'}"
                )
            )
        tokens = args.split(maxsplit=1)
        profile = detect_provider_profile(profile=tokens[0].strip())
        runtime.settings.provider.provider = profile.name
        runtime.settings.provider.profile = profile.name
        runtime.settings.provider.api_format = profile.api_format
        runtime.settings.provider.auth_scheme = profile.auth_scheme
        runtime.settings.provider.base_url = profile.default_base_url
        runtime.settings.provider.api_key_env = profile.default_api_key_env
        if len(tokens) == 2 and tokens[1].strip():
            runtime.settings.model = tokens[1].strip()
        _save_runtime_settings(runtime)
        return SlashCommandResult(
            message=(
                f"Updated provider to {profile.name}\n"
                f"Base URL: {runtime.settings.provider.base_url}\n"
                f"API key env: {runtime.settings.provider.api_key_env}\n"
                f"Model: {runtime.settings.model}"
            )
        )

    def _login_handler(args: str, context: SlashCommandContext) -> SlashCommandResult:
        runtime = context.runtime
        api_key = args.strip()
        if not api_key:
            api_key = context.prompt_fn("API key> ").strip()
        if not api_key:
            return SlashCommandResult(message="Login cancelled.")
        runtime.settings.provider.api_key = api_key
        _save_runtime_settings(runtime)
        return SlashCommandResult(
            message="Saved API key for the current session. Workspace settings keep only the API key env name."
        )

    def _logout_handler(_: str, context: SlashCommandContext) -> SlashCommandResult:
        runtime = context.runtime
        runtime.settings.provider.api_key = None
        _save_runtime_settings(runtime)
        return SlashCommandResult(message="Cleared the in-session API key. Workspace settings no longer contain an inline secret.")

    def _setup_handler(_: str, context: SlashCommandContext) -> SlashCommandResult:
        runtime = context.runtime
        profile_names = ", ".join(sorted(PROVIDER_PROFILES.keys()))
        profile_input = context.prompt_fn(
            f"Provider profile [{runtime.settings.provider.profile or runtime.settings.provider.provider}] ({profile_names}, or auto)> "
        ).strip()
        profile_name = profile_input or (runtime.settings.provider.profile if runtime.settings.provider.profile != "auto" else runtime.settings.provider.provider)
        model_input = context.prompt_fn(f"Model [{runtime.settings.model}]> ").strip()
        preview_profile = (
            detect_provider_profile(profile=profile_name)
            if profile_name and profile_name.lower() != "auto"
            else detect_provider_profile(
                base_url=runtime.settings.provider.base_url,
                model=model_input or runtime.settings.model,
            )
        )
        api_key_input = context.prompt_fn("API key (leave blank to keep current)> ").strip()
        base_url_input = context.prompt_fn(f"Base URL [{preview_profile.default_base_url}]> ").strip()

        resolved_model = model_input or runtime.settings.model
        resolved_base_url = base_url_input or preview_profile.default_base_url
        try:
            profile = (
                detect_provider_profile(profile=profile_name)
                if profile_name and profile_name.lower() != "auto"
                else detect_provider_profile(base_url=resolved_base_url, model=resolved_model)
            )
        except Exception as exc:
            return SlashCommandResult(message=f"Invalid provider profile: {exc}")

        auto_detected_profile = detect_provider_profile(base_url=resolved_base_url, model=resolved_model)
        warning = ""
        if profile.name != auto_detected_profile.name:
            profile = auto_detected_profile
            warning = (
                f"Adjusted provider profile to {profile.name} based on model/base URL compatibility.\n"
            )

        runtime.settings.provider.provider = profile.name
        runtime.settings.provider.profile = profile.name
        runtime.settings.provider.api_format = profile.api_format
        runtime.settings.provider.auth_scheme = profile.auth_scheme
        runtime.settings.provider.api_key_env = profile.default_api_key_env
        runtime.settings.provider.base_url = resolved_base_url
        runtime.settings.model = resolved_model
        if api_key_input:
            runtime.settings.provider.api_key = api_key_input
        _save_runtime_settings(runtime)
        return SlashCommandResult(
            message=(
                f"{warning}Setup complete.\n"
                f"Provider: {runtime.settings.provider.profile}\n"
                f"Model: {runtime.settings.model}\n"
                f"Base URL: {runtime.settings.provider.base_url}\n"
                f"API key saved: {'yes' if bool(runtime.settings.provider.api_key) else 'no'}"
            )
        )

    def _permissions_handler(args: str, context: SlashCommandContext) -> SlashCommandResult:
        runtime = context.runtime
        if not args:
            pending = len(runtime.list_approvals(status="pending"))
            return SlashCommandResult(
                message=f"Permission mode: {runtime.settings.permission.mode}\nPending approvals: {pending}"
            )
        mode = normalize_permission_mode(args.strip())
        if mode not in {"default", "plan", "full-access"}:
            return SlashCommandResult(message="Usage: /permissions [default|plan|full-access]")
        runtime.settings.permission.mode = mode
        _save_runtime_settings(runtime)
        return SlashCommandResult(message=f"Updated permission mode to {mode}")

    def _evo_mode_handler(args: str, context: SlashCommandContext) -> SlashCommandResult:
        runtime = context.runtime
        current_mode = (
            str(runtime.settings.runtime.auto_self_evolution_mode or "off").strip().lower()
            if runtime.settings.runtime.auto_self_evolution
            else "off"
        )
        if not args:
            return SlashCommandResult(
                message=(
                    f"Evolution mode: {current_mode}\n"
                    f"Auto self-evolution enabled: {'yes' if runtime.settings.runtime.auto_self_evolution else 'no'}"
                )
            )

        mode = args.strip().lower().replace("_", "-")
        aliases = {
            "off": "off",
            "candidate": "candidate",
            "auto": "auto",
            "apply": "apply",
            "promote": "promote",
        }
        normalized = aliases.get(mode)
        if normalized is None:
            return SlashCommandResult(message="Usage: /evo-mode [off|candidate|auto|apply|promote]")

        runtime.settings.runtime.auto_self_evolution = normalized != "off"
        runtime.settings.runtime.auto_self_evolution_mode = normalized
        _save_runtime_settings(runtime)
        return SlashCommandResult(
            message=(
                f"Updated evolution mode to {normalized}\n"
                f"Auto self-evolution enabled: {'yes' if runtime.settings.runtime.auto_self_evolution else 'no'}"
            )
        )

    def _approvals_handler(args: str, context: SlashCommandContext) -> SlashCommandResult:
        runtime = context.runtime
        tokens = args.split(maxsplit=2)
        if not tokens:
            pending = runtime.list_approvals(status="pending")
            if not pending:
                return SlashCommandResult(message="No pending approvals.")
            lines = ["Pending approvals:"]
            for item in pending:
                lines.append(f"- {item['id']} {item['tool_name']} :: {item['reason']}")
            return SlashCommandResult(message="\n".join(lines))
        if tokens[0] in {"approve", "deny"} and len(tokens) >= 2:
            approved = tokens[0] == "approve"
            note = tokens[2] if len(tokens) == 3 else ""
            try:
                request = runtime.approval_manager.decide(tokens[1], approved=approved, note=note)
            except Exception as exc:
                return SlashCommandResult(message=f"Approval update failed: {exc}")
            return SlashCommandResult(message=f"{request.id} -> {request.status}")
        return SlashCommandResult(message="Usage: /approvals [approve ID [NOTE]|deny ID [NOTE]]")

    def _sessions_handler(_: str, context: SlashCommandContext) -> SlashCommandResult:
        sessions = list_session_snapshots(context.runtime.workspace, limit=20)
        if not sessions:
            return SlashCommandResult(message="No saved sessions found.")
        lines = ["Saved sessions:"]
        for index, item in enumerate(sessions, start=1):
            ts = time.strftime("%m/%d %H:%M", time.localtime(item.get("created_at", 0)))
            lines.append(
                f"{index:>2}. {item.get('session_id')}  {ts}  {item.get('message_count')}msg  {item.get('summary') or '(no summary)'}"
            )
        return SlashCommandResult(message="\n".join(lines))

    def _resume_handler(args: str, context: SlashCommandContext) -> SlashCommandResult:
        sessions = list_session_snapshots(context.runtime.workspace, limit=20)
        if not args:
            if not sessions:
                return SlashCommandResult(message="No saved sessions found.")
            lines = ["Resume Session", "Select a session by number or session id:", ""]
            for index, item in enumerate(sessions, start=1):
                ts = time.strftime("%m/%d %H:%M", time.localtime(item.get("created_at", 0)))
                lines.append(
                    f"{index:>2}. {item.get('session_id')}  {ts}  {item.get('message_count')}msg  {item.get('summary') or '(no summary)'}"
                )
            choice = context.prompt_fn("\n".join(lines) + "\nresume> ").strip()
            if not choice:
                return SlashCommandResult(message="Resume cancelled.")
            session_id = _resolve_session_choice(choice, sessions)
            if session_id is None:
                return SlashCommandResult(message=f"Unknown session selection: {choice}")
        else:
            session_id = args.strip()
        if context.engine.load_session(session_id):
            return SlashCommandResult(message=f"Resumed session {session_id}")
        return SlashCommandResult(message=f"Session not found: {session_id}")

    def _commands_handler(args: str, context: SlashCommandContext) -> SlashCommandResult:
        runtime = context.runtime
        commands = load_workspace_commands(runtime.workspace, settings=runtime.settings)
        if not commands:
            return SlashCommandResult(message="No workspace commands found.")
        if args.startswith("show "):
            name = args[len("show ") :].strip()
            command = runtime.get_command(name)
            if command is None:
                return SlashCommandResult(message=f"Command not found: {name}")
            return SlashCommandResult(message=command.content)
        lines = ["Workspace commands:"]
        active_name = runtime.active_command.name if runtime.active_command is not None else None
        for command in commands:
            marker = "*" if command.name == active_name else "-"
            lines.append(f"{marker} /{command.name}: {command.description}")
        return SlashCommandResult(message="\n".join(lines))

    def _command_handler(args: str, context: SlashCommandContext) -> SlashCommandResult:
        runtime = context.runtime
        if not args:
            if runtime.active_command is None:
                return SlashCommandResult(message="No active command.")
            return SlashCommandResult(
                message=(
                    f"Active command: {runtime.active_command.name}\n"
                    f"Arguments: {runtime.active_command_arguments or '(none)'}"
                )
            )
        normalized = args.strip().lower()
        if normalized in {"clear", "none", "off"}:
            runtime.clear_active_command()
            return SlashCommandResult(message="Cleared active command.")
        name, _, command_args = args.partition(" ")
        return _activate_workspace_command(name.strip(), command_args.strip(), context)

    def _agents_handler(_: str, context: SlashCommandContext) -> SlashCommandResult:
        args = _.strip()
        runtime = context.runtime
        if args.startswith("run "):
            payload = args[len("run ") :].strip()
            name, separator, task = payload.partition("::")
            if not separator or not name.strip() or not task.strip():
                return SlashCommandResult(message="Usage: /agents run NAME :: TASK")
            agent = runtime.get_agent(name.strip())
            if agent is None:
                return SlashCommandResult(message=f"Agent not found: {name.strip()}")
            try:
                provider = build_live_provider(settings=runtime.settings)
                result = run_subagent(runtime, agent=agent, task=task.strip(), provider=provider)
            except Exception as exc:
                return SlashCommandResult(message=f"Subagent run failed: {exc}")
            return SlashCommandResult(message=json.dumps(result.to_dict(), indent=2, ensure_ascii=False))

        agents = runtime.list_agents()
        if not agents:
            return SlashCommandResult(message="No agents found.")
        return SlashCommandResult(
            message="\n".join(f"- {item['name']}: {item['description']}" for item in agents)
        )

    def _plugins_handler(args: str, context: SlashCommandContext) -> SlashCommandResult:
        runtime = context.runtime
        tokens = args.split()
        if not tokens or tokens[0] == "list":
            plugins = _discovered_plugins(runtime)
            if not plugins:
                return SlashCommandResult(message="No plugins found.")
            lines = ["Plugins:"]
            for plugin in plugins:
                state = "enabled" if plugin["enabled"] else "disabled"
                source = plugin.get("source", "unknown")
                lines.append(f"- {plugin['name']} [{state}] [{source}] {plugin.get('description', '')}")
            return SlashCommandResult(message="\n".join(lines))
        if tokens[0] == "show" and len(tokens) >= 2:
            name = tokens[1]
            plugin = _find_discovered_plugin(runtime, name)
            if plugin is None:
                return SlashCommandResult(message=f"Plugin not found: {name}")
            return SlashCommandResult(message=json.dumps(plugin, indent=2, ensure_ascii=False))
        if tokens[0] in {"enable", "disable"} and len(tokens) >= 2:
            name = tokens[1]
            runtime.settings.enabled_plugins[name] = tokens[0] == "enable"
            _save_runtime_settings(runtime)
            return SlashCommandResult(message=f"{'Enabled' if tokens[0] == 'enable' else 'Disabled'} plugin {name}")
        if tokens[0] == "marketplaces":
            marketplaces = load_marketplaces(runtime.workspace, runtime.settings)
            if not marketplaces:
                return SlashCommandResult(message="No marketplaces available.")
            lines = ["Marketplaces:"]
            for marketplace in marketplaces:
                lines.append(f"- {marketplace.name}: {marketplace.description or '(no description)'}")
                for plugin in marketplace.plugins:
                    lines.append(f"    * {plugin.name}: {plugin.description}")
            return SlashCommandResult(message="\n".join(lines))
        if tokens[0] == "install" and len(tokens) >= 3:
            marketplace_name = tokens[1]
            plugin_name = tokens[2]
            try:
                path = install_marketplace_plugin(
                    runtime.workspace,
                    marketplace_name=marketplace_name,
                    plugin_name=plugin_name,
                    settings=runtime.settings,
                )
            except Exception as exc:
                return SlashCommandResult(message=f"Plugin install failed: {exc}")
            runtime.settings.enabled_plugins[plugin_name] = True
            _save_runtime_settings(runtime)
            return SlashCommandResult(message=f"Installed plugin {plugin_name} from {marketplace_name} -> {path}")
        return SlashCommandResult(
            message="Usage: /plugins [list|show NAME|enable NAME|disable NAME|marketplaces|install MARKETPLACE PLUGIN]"
        )

    def _skills_handler(args: str, context: SlashCommandContext) -> SlashCommandResult:
        skills = load_workspace_skills(context.runtime.workspace, settings=context.runtime.settings)
        if not skills:
            return SlashCommandResult(message="No skills found.")
        if args:
            requested = args.strip().lower()
            for skill in skills:
                if skill.name.lower() == requested:
                    return SlashCommandResult(message=skill.content)
            return SlashCommandResult(message=f"Skill not found: {args.strip()}")
        return SlashCommandResult(
            message="\n".join(f"- {skill.name}: {skill.description}" for skill in skills)
        )

    def _memory_handler(args: str, context: SlashCommandContext) -> SlashCommandResult:
        runtime = context.runtime
        if not args or args.strip() == "list":
            entries = list_memory_entries(runtime.workspace)
            if not entries:
                return SlashCommandResult(message="No memory entries.")
            return SlashCommandResult(message="\n".join(f"- {path.name}" for path in entries))
        if args.startswith("add "):
            title, separator, content = args[len("add ") :].partition("::")
            if not separator or not title.strip() or not content.strip():
                return SlashCommandResult(message="Usage: /memory add TITLE :: CONTENT")
            path = add_memory_entry(runtime.workspace, title.strip(), content.strip())
            return SlashCommandResult(message=f"Added memory entry {path.name}")
        if args.startswith("remove "):
            name = args[len("remove ") :].strip()
            removed = remove_memory_entry(runtime.workspace, name)
            return SlashCommandResult(message=f"{'Removed' if removed else 'Not found'} memory entry {name}")
        return SlashCommandResult(message="Usage: /memory [list|add TITLE :: CONTENT|remove NAME]")

    def _mcp_handler(_: str, context: SlashCommandContext) -> SlashCommandResult:
        runtime = context.runtime
        payload = {
            "servers": runtime.list_mcp_servers(),
            "tools": runtime.list_mcp_tools(),
            "resources": runtime.list_mcp_resources(),
            "prompts": runtime.list_mcp_prompts(),
        }
        return SlashCommandResult(message=json.dumps(payload, indent=2, ensure_ascii=False))

    def _doctor_handler(_: str, context: SlashCommandContext) -> SlashCommandResult:
        from evo_harness.cli import _build_doctor_report

        payload = _build_doctor_report(context.runtime.workspace, settings_path=context.runtime.settings_path)
        return SlashCommandResult(message=json.dumps(payload, indent=2, ensure_ascii=False))

    def _config_handler(args: str, context: SlashCommandContext) -> SlashCommandResult:
        runtime = context.runtime
        if not args:
            return SlashCommandResult(message=json.dumps(runtime.settings.to_dict(), indent=2, ensure_ascii=False))
        if args.strip() == "list":
            return SlashCommandResult(message="\n".join(f"- {key}" for key in sorted(runtime.settings.to_dict().keys())))
        if args.startswith("show "):
            key_path = args[len("show ") :].strip()
            try:
                value = _get_nested_setting(runtime.settings, key_path)
            except Exception as exc:
                return SlashCommandResult(message=f"Config lookup failed: {exc}")
            return SlashCommandResult(message=_render_value(value))
        if args.startswith("get "):
            key_path = args[len("get ") :].strip()
            try:
                value = _get_nested_setting(runtime.settings, key_path)
            except Exception as exc:
                return SlashCommandResult(message=f"Config lookup failed: {exc}")
            return SlashCommandResult(message=_render_value(value))
        if args.startswith("set "):
            payload = args[len("set ") :].strip()
            key_path, _, raw_value = payload.partition(" ")
            if not key_path or not raw_value.strip():
                return SlashCommandResult(message="Usage: /config set KEY_PATH VALUE")
            try:
                _set_nested_setting(runtime.settings, key_path.strip(), raw_value.strip())
            except Exception as exc:
                return SlashCommandResult(message=f"Config update failed: {exc}")
            _save_runtime_settings(runtime)
            return SlashCommandResult(message=f"Updated {key_path.strip()}")
        if args.startswith("unset "):
            key_path = args[len("unset ") :].strip()
            try:
                _unset_nested_setting(runtime.settings, key_path)
            except Exception as exc:
                return SlashCommandResult(message=f"Config unset failed: {exc}")
            _save_runtime_settings(runtime)
            return SlashCommandResult(message=f"Reset {key_path}")
        return SlashCommandResult(message="Usage: /config [list|show KEY_PATH|get KEY_PATH|set KEY_PATH VALUE|unset KEY_PATH]")

    def _history_handler(args: str, context: SlashCommandContext) -> SlashCommandResult:
        limit = 12
        if args:
            try:
                limit = max(1, int(args))
            except ValueError:
                return SlashCommandResult(message="Usage: /history [COUNT]")
        messages = context.runtime.messages[-limit:]
        if not messages:
            return SlashCommandResult(message="No conversation history yet.")
        lines = []
        for item in messages:
            role = item.get("role", "unknown")
            text = str(item.get("text", "")).strip()
            if text:
                lines.append(f"{role}: {text[:240]}")
        return SlashCommandResult(message="\n".join(lines) if lines else "No printable history.")

    def _analytics_handler(_: str, context: SlashCommandContext) -> SlashCommandResult:
        payload = session_analytics_report(context.runtime.workspace, limit=20)
        return SlashCommandResult(message=json.dumps(payload, indent=2, ensure_ascii=False))

    def _tasks_handler(args: str, context: SlashCommandContext) -> SlashCommandResult:
        manager = get_task_manager(context.runtime.workspace)
        tokens = args.split(maxsplit=1)
        if not tokens or tokens[0] == "list":
            payload = [item.to_dict() for item in manager.list_tasks()]
            return SlashCommandResult(message=json.dumps(payload, indent=2, ensure_ascii=False))
        action = tokens[0]
        remainder = tokens[1].strip() if len(tokens) == 2 else ""
        try:
            if action == "run":
                if not remainder:
                    return SlashCommandResult(message="Usage: /tasks run COMMAND")
                record = manager.create_shell_task(command=remainder, description="chat task")
                return SlashCommandResult(message=json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
            if action == "get":
                if not remainder:
                    return SlashCommandResult(message="Usage: /tasks get ID")
                record = manager.get_task(remainder)
                if record is None:
                    return SlashCommandResult(message=f"Task not found: {remainder}")
                return SlashCommandResult(message=json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
            if action == "wait":
                if not remainder:
                    return SlashCommandResult(message="Usage: /tasks wait ID")
                record = manager.wait_task(remainder, timeout_s=30.0)
                return SlashCommandResult(message=json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
            if action == "output":
                if not remainder:
                    return SlashCommandResult(message="Usage: /tasks output ID")
                payload = {"id": remainder, "output": manager.read_task_output(remainder, max_bytes=4000)}
                return SlashCommandResult(message=json.dumps(payload, indent=2, ensure_ascii=False))
            if action == "stop":
                if not remainder:
                    return SlashCommandResult(message="Usage: /tasks stop ID")
                record = manager.stop_task(remainder)
                return SlashCommandResult(message=json.dumps(record.to_dict(), indent=2, ensure_ascii=False))
        except Exception as exc:
            return SlashCommandResult(message=f"Task command failed: {exc}")
        return SlashCommandResult(message="Usage: /tasks [list|run COMMAND|get ID|wait ID|output ID|stop ID]")

    def _evolve_handler(args: str, context: SlashCommandContext) -> SlashCommandResult:
        runtime = context.runtime
        tokens = args.split()
        action = tokens[0].lower() if tokens else "plan"
        capabilities = runtime.evolution_capabilities()
        try:
            if action == "plan":
                assessment = _try_autonomous_assessment(runtime)
                plan = plan_from_saved_session(runtime.workspace, capabilities=capabilities, assessment=assessment)
                payload = {
                    "operator": plan.proposal.operator,
                    "safe_to_apply": plan.safe_to_apply,
                    "reason": plan.proposal.reason,
                    "autonomous_assessment": assessment.to_dict() if assessment is not None else None,
                    "bundle_name": plan.change_request.get("bundle_name"),
                    "change_targets": plan.proposal.change_targets,
                    "preferred_path": plan.change_request.get("preferred_path"),
                    "target_memory": plan.change_request.get("target_memory"),
                    "risk_score": plan.report.risk_score,
                }
                return SlashCommandResult(message=json.dumps(payload, indent=2, ensure_ascii=False))

            if action in {"candidate", "apply", "promote", "auto"}:
                assessment = _try_autonomous_assessment(runtime)
                plan = plan_from_saved_session(runtime.workspace, capabilities=capabilities, assessment=assessment)
                allow_unvalidated = "force" in {item.lower() for item in tokens[1:]}
                execution = ControlledEvolutionExecutor().execute(
                    plan,
                    workspace_root=runtime.workspace,
                    mode=action,
                    run_validation=action in {"apply", "promote", "auto"},
                    allow_unvalidated_promotion=allow_unvalidated,
                )
                record_path = write_execution_record(runtime.workspace, plan=plan, execution=execution)
                payload = {
                    "mode": action,
                    "operator": plan.proposal.operator,
                    "success": execution.success,
                    "promotion_state": execution.promotion_state,
                    "autonomous_assessment": assessment.to_dict() if assessment is not None else None,
                    "bundle_name": plan.change_request.get("bundle_name"),
                    "created_paths": execution.created_paths,
                    "applied_paths": execution.applied_paths,
                    "record_path": str(record_path),
                }
                return SlashCommandResult(message=json.dumps(payload, indent=2, ensure_ascii=False))

            if action == "rollback":
                result = rollback_execution(runtime.workspace)
                return SlashCommandResult(message=json.dumps(result.to_dict(), indent=2, ensure_ascii=False))

            if action == "report":
                payload = promotion_report(runtime.workspace)
                return SlashCommandResult(message=json.dumps(payload, indent=2, ensure_ascii=False))
        except Exception as exc:
            return SlashCommandResult(message=f"Evolution action failed: {exc}")

        return SlashCommandResult(message="Usage: /evolve [plan|candidate|apply|promote [force]|auto|rollback|report]")

    def _init_handler(args: str, context: SlashCommandContext) -> SlashCommandResult:
        from evo_harness.onboarding import initialize_workspace

        force = args.strip().lower() in {"force", "--force"}
        result = initialize_workspace(context.runtime.workspace, force=force)
        _reload_runtime_state(context.runtime)
        return SlashCommandResult(message=json.dumps(result.to_dict(), indent=2, ensure_ascii=False))

    registry.register(SlashCommand("help", "Show available slash commands", _help_handler))
    registry.register(SlashCommand("exit", "Exit the session", _exit_handler))
    registry.register(SlashCommand("clear", "Clear conversation history", _clear_handler))
    registry.register(SlashCommand("status", "Show current session status", _status_handler))
    registry.register(SlashCommand("model", "Show or update the current model", _model_handler))
    registry.register(SlashCommand("login", "Save an API key in-session", _login_handler))
    registry.register(SlashCommand("logout", "Clear the saved API key", _logout_handler))
    registry.register(SlashCommand("provider", "Show or update the current provider profile", _provider_handler))
    registry.register(SlashCommand("setup", "Interactive provider setup", _setup_handler))
    registry.register(SlashCommand("permissions", "Show or update permission mode", _permissions_handler))
    registry.register(SlashCommand("evo-mode", "Show or update auto self-evolution mode", _evo_mode_handler))
    registry.register(SlashCommand("approvals", "List or decide queued approvals", _approvals_handler))
    registry.register(SlashCommand("sessions", "List saved sessions", _sessions_handler))
    registry.register(SlashCommand("resume", "Resume a saved session", _resume_handler))
    registry.register(SlashCommand("commands", "List workspace commands", _commands_handler))
    registry.register(SlashCommand("command", "Show, clear, or activate one command", _command_handler))
    registry.register(SlashCommand("agents", "List available agents", _agents_handler))
    registry.register(SlashCommand("tasks", "Inspect or run background tasks", _tasks_handler))
    registry.register(SlashCommand("plugins", "Manage plugins in-session", _plugins_handler))
    registry.register(SlashCommand("skills", "List or show available skills", _skills_handler))
    registry.register(SlashCommand("memory", "Inspect or edit workspace memory", _memory_handler))
    registry.register(SlashCommand("mcp", "Show MCP registry state", _mcp_handler))
    registry.register(SlashCommand("doctor", "Run a workspace doctor report", _doctor_handler))
    registry.register(SlashCommand("config", "Show or set configuration values", _config_handler))
    registry.register(SlashCommand("history", "Show recent message history", _history_handler))
    registry.register(SlashCommand("analytics", "Show session analytics", _analytics_handler))
    registry.register(SlashCommand("evolve", "Plan or execute controlled self-evolution actions", _evolve_handler, hidden=True))
    registry.register(SlashCommand("init", "Initialize Evo Harness in this workspace", _init_handler))
    return registry


def format_session_banner(runtime: HarnessRuntime) -> str:
    active_command = runtime.active_command.name if runtime.active_command is not None else "-"
    profile = detect_provider_profile(
        provider=runtime.settings.provider.provider,
        profile=runtime.settings.provider.profile,
        base_url=runtime.settings.provider.base_url,
        model=runtime.settings.model,
    )
    workspace_name = Path(runtime.workspace).name
    lines = [
        "=" * 78,
        f"Evo Harness  |  workspace: {workspace_name}",
        "type a request to send it, or use slash commands to steer the session",
        "/help  /setup  /login  /resume  /model  /provider  /permissions  /evo-mode  /config  /plugins  /exit",
        "-" * 78,
        f"model: {runtime.settings.model} | provider: {profile.name} | mode: {runtime.settings.permission.mode} | command: {active_command}",
        f"sessions: {len(list_session_snapshots(runtime.workspace, limit=20))} | approvals: {len(runtime.list_approvals(status='pending'))}",
        "=" * 78,
    ]
    return "\n".join(lines)


def format_prompt_label(runtime: HarnessRuntime) -> str:
    active = runtime.active_command.name if runtime.active_command is not None else "-"
    return f"[{runtime.settings.model} | {runtime.settings.permission.mode} | {active}] > "


def _dispatch_workspace_command(
    name: str,
    arguments: str,
    context: SlashCommandContext,
) -> SlashCommandResult | None:
    if not name:
        return None
    command = context.runtime.get_command(name)
    if command is None:
        return None
    return _activate_workspace_command(name, arguments, context)


def _activate_workspace_command(
    name: str,
    arguments: str,
    context: SlashCommandContext,
) -> SlashCommandResult:
    try:
        rendered = context.runtime.set_active_command(name, arguments)
    except KeyError:
        return SlashCommandResult(message=f"Command not found: {name}")
    return SlashCommandResult(message=rendered)


def _save_runtime_settings(runtime: HarnessRuntime) -> None:
    provider_api_key = runtime.settings.provider.api_key
    tavily_api_key = runtime.settings.search.tavily_api_key
    exa_api_key = runtime.settings.search.exa_api_key
    path = runtime.settings_path or (Path(runtime.workspace).resolve() / ".evo-harness" / "settings.json")
    save_settings(runtime.settings, path)
    _reload_runtime_state(runtime)
    runtime.settings.provider.api_key = provider_api_key
    runtime.settings.search.tavily_api_key = tavily_api_key
    runtime.settings.search.exa_api_key = exa_api_key


def _reload_runtime_state(runtime: HarnessRuntime) -> None:
    runtime.settings = load_settings(runtime.settings_path, workspace=runtime.workspace)
    runtime.permission_checker = PermissionChecker(
        runtime.settings.permission,
        sandbox=runtime.settings.sandbox,
        workspace=runtime.workspace,
    )
    runtime.approval_manager = ApprovalManager(runtime.workspace, runtime.settings.approvals)
    hook_defs = [] if runtime.settings.managed.allow_managed_hooks_only else load_workspace_hooks(runtime.workspace)
    runtime.hook_executor = HookExecutor(hook_defs)


def _set_nested_setting(settings, key_path: str, raw_value: str) -> None:
    cursor = settings
    parts = key_path.split(".")
    for part in parts[:-1]:
        cursor = _resolve_child(cursor, part)
    last = parts[-1]
    if isinstance(cursor, dict):
        current = cursor.get(last)
        if current is None:
            raise KeyError(last)
        cursor[last] = _coerce_value(raw_value, current)
        return
    if not hasattr(cursor, last):
        raise KeyError(last)
    current = getattr(cursor, last)
    coerced = _coerce_value(raw_value, current)
    setattr(cursor, last, coerced)


def _get_nested_setting(settings, key_path: str):
    cursor = settings
    for part in key_path.split("."):
        cursor = _resolve_child(cursor, part)
    return cursor


def _unset_nested_setting(settings, key_path: str) -> None:
    defaults = type(settings)()
    default_value = _get_nested_setting(defaults, key_path)
    _set_nested_value(settings, key_path, default_value)


def _set_nested_value(settings, key_path: str, value) -> None:
    cursor = settings
    parts = key_path.split(".")
    for part in parts[:-1]:
        cursor = _resolve_child(cursor, part)
    last = parts[-1]
    if isinstance(cursor, dict):
        cursor[last] = value
        return
    setattr(cursor, last, value)


def _resolve_child(cursor, part: str):
    if isinstance(cursor, dict):
        if part not in cursor:
            raise KeyError(part)
        return cursor[part]
    if not hasattr(cursor, part):
        raise KeyError(part)
    return getattr(cursor, part)


def _render_value(value) -> str:
    if hasattr(value, "to_dict"):
        return json.dumps(value.to_dict(), indent=2, ensure_ascii=False)
    if hasattr(value, "__dataclass_fields__"):
        return json.dumps(asdict(value), indent=2, ensure_ascii=False)
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, ensure_ascii=False)
    return str(value)


def _resolve_session_choice(choice: str, sessions: list[dict[str, object]]) -> str | None:
    if choice.isdigit():
        index = int(choice)
        if 1 <= index <= len(sessions):
            return str(sessions[index - 1]["session_id"])
        return None
    for item in sessions:
        if str(item.get("session_id")) == choice:
            return choice
    return None


def _discovered_plugins(runtime: HarnessRuntime) -> list[dict[str, object]]:
    settings = runtime.settings
    payload: list[dict[str, object]] = []
    for path, source in discover_plugin_paths(runtime.workspace):
        manifest_path = _find_plugin_manifest(path)
        if manifest_path is None:
            continue
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        name = str(raw.get("name", path.name))
        payload.append(
            {
                "name": name,
                "description": str(raw.get("description", "")),
                "version": str(raw.get("version", "0.0.0")),
                "enabled": settings.enabled_plugins.get(name, bool(raw.get("enabled_by_default", True))),
                "source": source,
                "path": str(path),
                "manifest_path": str(manifest_path),
            }
        )
    payload.sort(key=lambda item: str(item["name"]).lower())
    return payload


def _find_discovered_plugin(runtime: HarnessRuntime, name: str) -> dict[str, object] | None:
    lowered = name.lower()
    for plugin in _discovered_plugins(runtime):
        if str(plugin["name"]).lower() == lowered:
            return plugin
    return None


def _find_plugin_manifest(plugin_dir: Path) -> Path | None:
    for candidate in (
        plugin_dir / "plugin.json",
        plugin_dir / ".claude-plugin" / "plugin.json",
        plugin_dir / ".openharness-plugin" / "plugin.json",
        plugin_dir / ".evo-harness-plugin" / "plugin.json",
    ):
        if candidate.exists():
            return candidate
    return None


def _try_autonomous_assessment(runtime: HarnessRuntime):
    try:
        provider = build_live_provider(settings=runtime.settings)
    except Exception:
        return None
    try:
        return assess_saved_session(runtime.workspace, settings=runtime.settings, provider=provider)
    except Exception:
        return None


def _coerce_value(raw_value: str, current):
    lowered = raw_value.lower()
    if isinstance(current, bool):
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Invalid boolean value: {raw_value}")
    if isinstance(current, int) and not isinstance(current, bool):
        return int(raw_value)
    if isinstance(current, float):
        return float(raw_value)
    if isinstance(current, list):
        if raw_value.strip().startswith("["):
            parsed = json.loads(raw_value)
            if not isinstance(parsed, list):
                raise ValueError("Expected a JSON list value")
            return parsed
        return [item.strip() for item in raw_value.split(",") if item.strip()]
    if isinstance(current, dict):
        parsed = json.loads(raw_value)
        if not isinstance(parsed, dict):
            raise ValueError("Expected a JSON object value")
        return parsed
    return raw_value
