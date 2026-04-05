from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from evo_harness.harness.agents import AgentDefinition, find_agent, load_workspace_agents
from evo_harness.harness.approvals import ApprovalManager, ApprovalRequest
from evo_harness.harness.content_windows import context_safe_output
from evo_harness.harness.commands import CommandDefinition, find_command, load_workspace_commands
from evo_harness.harness.hooks import HookExecutor, load_workspace_hooks
from evo_harness.harness.messages import ChatMessage
from evo_harness.harness.mcp import (
    list_mcp_prompts,
    list_mcp_resources,
    list_mcp_servers,
    list_mcp_tools,
)
from evo_harness.harness.permissions import PermissionChecker
from evo_harness.harness.prompts import build_system_prompt
from evo_harness.harness.plugins import load_workspace_plugins
from evo_harness.harness.session import save_session_snapshot
from evo_harness.harness.session import list_session_snapshots
from evo_harness.harness.settings import HarnessSettings, load_settings
from evo_harness.harness.skills import load_workspace_skills
from evo_harness.harness.tasks import get_task_manager
from evo_harness.harness.tools import ToolExecutionContext, ToolRegistry, ToolResult, create_default_tool_registry


@dataclass(slots=True)
class RuntimeEvent:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "payload": self.payload}


@dataclass(slots=True)
class ToolInvocationRecord:
    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    tool_call_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PreparedToolExecution:
    tool_name: str
    tool: Any
    arguments: dict[str, Any]
    file_path: str | None = None
    shell_command: str | None = None


class HarnessRuntime:
    """A minimal but real harness runtime for workspace-native experimentation."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        settings_path: str | Path | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.settings_path = Path(settings_path).resolve() if settings_path is not None else None
        self.settings: HarnessSettings = load_settings(settings_path, workspace=self.workspace)
        self.permission_checker = PermissionChecker(
            self.settings.permission,
            sandbox=self.settings.sandbox,
            workspace=self.workspace,
        )
        self.approval_manager = ApprovalManager(self.workspace, self.settings.approvals)
        self.tool_registry = tool_registry or create_default_tool_registry()
        hook_defs = [] if self.settings.managed.allow_managed_hooks_only else load_workspace_hooks(self.workspace)
        self.hook_executor = HookExecutor(hook_defs)
        self.messages: list[dict[str, Any]] = []
        self.tool_history: list[ToolInvocationRecord] = []
        self.active_command: CommandDefinition | None = None
        self.active_command_arguments: str = ""
        self.current_provider_factory: Callable[[], Any] | None = None
        self.approval_prompt: Callable[[ApprovalRequest], bool] | None = None
        self.last_query_result: Any | None = None

    def reset(self) -> None:
        self.messages.clear()
        self.tool_history.clear()
        self.active_command = None
        self.active_command_arguments = ""
        self.current_provider_factory = None
        self.last_query_result = None

    def append_message(self, message: ChatMessage) -> None:
        self.messages.append(message.to_dict())

    def system_prompt(self, *, latest_user_prompt: str | None = None) -> str:
        return build_system_prompt(
            self.workspace,
            custom_prompt=self.settings.system_prompt,
            settings=self.settings,
            latest_user_prompt=latest_user_prompt,
        )

    def list_tools(self) -> list[dict[str, Any]]:
        return self.tool_registry.describe()

    def available_tools(self) -> list[dict[str, Any]]:
        if self.active_command is None or self.active_command.allowed_tools is None:
            return self.tool_registry.describe()
        return self.tool_registry.filtered(self.active_command.allowed_tools).describe()

    def list_commands(self) -> list[dict[str, Any]]:
        return [command.to_dict() for command in load_workspace_commands(self.workspace)]

    def list_agents(self) -> list[dict[str, Any]]:
        return [agent.to_dict() for agent in load_workspace_agents(self.workspace)]

    def list_plugins(self) -> list[dict[str, Any]]:
        return [plugin.to_dict() for plugin in load_workspace_plugins(self.workspace, settings=self.settings)]

    def list_skills(self) -> list[dict[str, Any]]:
        return [skill.to_dict() for skill in load_workspace_skills(self.workspace, settings=self.settings)]

    def list_mcp_servers(self) -> list[dict[str, Any]]:
        return list_mcp_servers(self.workspace, settings=self.settings)

    def list_mcp_tools(self) -> list[dict[str, Any]]:
        return list_mcp_tools(self.workspace, settings=self.settings)

    def list_mcp_resources(self) -> list[dict[str, Any]]:
        return list_mcp_resources(self.workspace, settings=self.settings)

    def list_mcp_prompts(self) -> list[dict[str, Any]]:
        return list_mcp_prompts(self.workspace, settings=self.settings)

    def list_tasks(self) -> list[dict[str, Any]]:
        return [task.to_dict() for task in get_task_manager(self.workspace).list_tasks()]

    def list_sessions(self) -> list[dict[str, Any]]:
        return list_session_snapshots(self.workspace)

    def list_approvals(self, *, status: str | None = None) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.approval_manager.list_requests(status=status)]

    def get_agent(self, name: str) -> AgentDefinition | None:
        return find_agent(self.workspace, name)

    def create_subruntime(self, *, tool_allowlist: list[str] | None = None) -> "HarnessRuntime":
        subruntime = HarnessRuntime(
            self.workspace,
            settings_path=self.settings_path,
            tool_registry=self.tool_registry.filtered(tool_allowlist),
        )
        subruntime.active_command = self.active_command
        subruntime.active_command_arguments = self.active_command_arguments
        subruntime.current_provider_factory = self.current_provider_factory
        subruntime.approval_prompt = self.approval_prompt
        return subruntime

    def get_command(self, name: str) -> CommandDefinition | None:
        return find_command(self.workspace, name)

    def render_command(self, name: str, arguments: str = "") -> str:
        command = self.get_command(name)
        if command is None:
            raise KeyError(f"Command not found: {name}")
        return command.render(arguments)

    def set_active_command(self, name: str, arguments: str = "") -> str:
        command = self.get_command(name)
        if command is None:
            raise KeyError(f"Command not found: {name}")
        self.active_command = command
        self.active_command_arguments = arguments
        return command.render(arguments)

    def clear_active_command(self) -> None:
        self.active_command = None
        self.active_command_arguments = ""

    def execute_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        tool_call_id: str | None = None,
    ) -> ToolResult:
        prepared, early_result = self.prepare_tool_execution(name, arguments)
        if early_result is not None:
            record_name = prepared.tool_name if prepared is not None else name
            self._record_tool(record_name, arguments, early_result, tool_call_id=tool_call_id)
            return early_result
        if prepared is None:
            result = ToolResult(output=f"Unknown tool: {name}", is_error=True)
            self._record_tool(name, arguments, result, tool_call_id=tool_call_id)
            return result

        result = self.execute_prepared_tool(prepared)
        self.finalize_prepared_tool(prepared, result, tool_call_id=tool_call_id)
        return result

    def prepare_tool_execution(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> tuple[PreparedToolExecution | None, ToolResult | None]:
        tool = self.tool_registry.get(name)
        if tool is None:
            return None, ToolResult(output=f"Unknown tool: {name}", is_error=True)
        canonical_name = tool.name

        if (
            self.active_command is not None
            and self.active_command.allowed_tools is not None
            and canonical_name not in self.active_command.allowed_tools
            and name not in self.active_command.allowed_tools
        ):
            return None, ToolResult(
                output=(
                    f"Tool {canonical_name} is not allowed by active command {self.active_command.name}. "
                    f"Allowed tools: {', '.join(self.active_command.allowed_tools)}"
                ),
                is_error=True,
                metadata={"blocked_by_command": self.active_command.name},
            )

        file_path = _candidate_file_path(arguments)
        shell_command = str(arguments.get("command", "")) or None
        if canonical_name == "bash" and shell_command:
            for pattern in self.settings.safety.blocked_shell_patterns:
                import fnmatch

                if fnmatch.fnmatch(shell_command, pattern):
                    return None, ToolResult(
                        output=f"Command matches blocked safety pattern: {pattern}",
                        is_error=True,
                        metadata={"blocked_by_safety_pattern": pattern},
                    )

        decision = self.permission_checker.evaluate(
            canonical_name,
            is_read_only=tool.is_read_only(arguments),
            file_path=file_path,
            command=shell_command,
        )
        if not decision.allowed:
            fingerprint = self.approval_manager.fingerprint(
                tool_name=canonical_name,
                arguments=arguments,
                command=shell_command,
                file_path=file_path,
            )
            cached_decision = self.approval_manager.get_cached_decision(fingerprint)
            if cached_decision is not None:
                if cached_decision.status == "approved":
                    decision = type(decision)(allowed=True, requires_confirmation=False, reason="Previously approved")
                elif cached_decision.status == "denied":
                    return None, ToolResult(
                        output=cached_decision.decision_note or decision.reason or f"Permission denied for {name}",
                        is_error=True,
                        metadata={
                            "requires_confirmation": False,
                            "approval_request_id": cached_decision.id,
                            "approval_status": cached_decision.status,
                        },
                    )

        if not decision.allowed:
            if decision.requires_confirmation:
                approval_request = self.approval_manager.submit_request(
                    tool_name=canonical_name,
                    arguments=arguments,
                    reason=decision.reason or f"Approval required for {canonical_name}",
                    command=shell_command,
                    file_path=file_path,
                )
                if self.approval_prompt is not None:
                    approved = bool(self.approval_prompt(approval_request))
                    decided = self.approval_manager.decide(
                        approval_request.id,
                        approved=approved,
                        note="Approved interactively" if approved else "Denied interactively",
                    )
                    if not approved:
                        return None, ToolResult(
                            output=decided.decision_note or decision.reason or f"Permission denied for {name}",
                            is_error=True,
                            metadata={
                                "requires_confirmation": False,
                                "approval_request_id": decided.id,
                                "approval_status": decided.status,
                            },
                        )
                elif self.settings.approvals.mode == "queue":
                    return None, ToolResult(
                        output=f"{decision.reason or f'Permission denied for {name}'} Approval request queued: {approval_request.id}",
                        is_error=True,
                        metadata={
                            "requires_confirmation": True,
                            "approval_request_id": approval_request.id,
                            "approval_status": approval_request.status,
                        },
                    )
                else:
                    return None, ToolResult(
                        output=decision.reason or f"Permission denied for {name}",
                        is_error=True,
                        metadata={"requires_confirmation": True},
                    )
            else:
                return None, ToolResult(
                    output=decision.reason or f"Permission denied for {name}",
                    is_error=True,
                    metadata={"requires_confirmation": decision.requires_confirmation},
                )

        pre_results = self.hook_executor.execute(
            "PreToolUse",
            {"tool_name": canonical_name, "tool_input": arguments},
            cwd=self.workspace,
        )
        blocked = next((item for item in pre_results if item.blocked), None)
        if blocked is not None:
            return None, ToolResult(output=blocked.reason or "PreToolUse blocked the action", is_error=True)

        return (
            PreparedToolExecution(
                tool_name=canonical_name,
                tool=tool,
                arguments=dict(arguments),
                file_path=file_path,
                shell_command=shell_command,
            ),
            None,
        )

    def execute_prepared_tool(self, prepared: PreparedToolExecution) -> ToolResult:
        return prepared.tool.execute(
            prepared.arguments,
            ToolExecutionContext(
                cwd=self.workspace,
                metadata={
                    "runtime": self,
                    "tool_registry": self.tool_registry,
                    "provider_factory": self.current_provider_factory,
                    "settings": self.settings,
                    "approval_manager": self.approval_manager,
                },
            ),
        )

    def finalize_prepared_tool(
        self,
        prepared: PreparedToolExecution,
        result: ToolResult,
        *,
        tool_call_id: str | None = None,
    ) -> None:
        self.hook_executor.execute(
            "PostToolUse",
            {
                "tool_name": prepared.tool_name,
                "tool_input": prepared.arguments,
                "tool_output": result.output,
                "tool_is_error": result.is_error,
            },
            cwd=self.workspace,
        )
        self._record_tool(prepared.tool_name, prepared.arguments, result, tool_call_id=tool_call_id)

    def run_script(self, path: str | Path) -> dict[str, Any]:
        import json

        script_path = Path(path).resolve()
        payload = json.loads(script_path.read_text(encoding="utf-8"))
        results: list[RuntimeEvent] = []

        for step in payload.get("steps", []):
            action = step.get("action")
            if action == "user":
                message = {"role": "user", "text": str(step.get("text", ""))}
                self.messages.append(message)
                results.append(RuntimeEvent(kind="user_message", payload=message))
                continue

            if action == "command":
                name = str(step["name"])
                rendered = self.set_active_command(name, str(step.get("arguments", "")))
                message = ChatMessage(role="assistant", text=rendered)
                self.append_message(message)
                results.append(RuntimeEvent(kind="command_rendered", payload={"name": name, "text": rendered}))
                continue

            if action == "tool":
                tool_name = str(step["tool"])
                arguments = dict(step.get("input", {}))
                result = self.execute_tool(tool_name, arguments)
                results.append(
                    RuntimeEvent(
                        kind="tool_result",
                        payload={
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "result": result.to_dict(),
                        },
                    )
                )
                continue

            results.append(RuntimeEvent(kind="unknown_step", payload={"step": step}))

        session_path = save_session_snapshot(
            workspace=self.workspace,
            model=self.settings.model,
            system_prompt=self.system_prompt(),
            messages=self.messages,
            usage={"tool_calls": len(self.tool_history)},
            metadata={
                "tool_history": [record.to_dict() for record in self.tool_history],
                "active_command": self.active_command.to_dict() if self.active_command else None,
                "active_command_arguments": self.active_command_arguments,
            },
        )

        return {
            "script": str(script_path),
            "events": [event.to_dict() for event in results],
            "tool_history": [record.to_dict() for record in self.tool_history],
            "session_path": str(session_path),
        }

    def _record_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        result: ToolResult,
        *,
        tool_call_id: str | None = None,
    ) -> None:
        record = ToolInvocationRecord(
            tool_name=name,
            arguments=dict(arguments),
            result=result.to_dict(),
            tool_call_id=tool_call_id,
        )
        self.tool_history.append(record)
        tool_text, tool_metadata = _context_safe_tool_output(result.output)
        self.append_message(
            ChatMessage(
                role="tool",
                text=tool_text,
                tool_name=name,
                is_error=result.is_error,
                metadata=_tool_message_metadata(
                    result.metadata,
                    {
                        **({"tool_call_id": tool_call_id} if tool_call_id else {}),
                        **tool_metadata,
                    },
                ),
            )
        )


def _candidate_file_path(arguments: dict[str, Any]) -> str | None:
    for key in ("path", "file_path"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _context_safe_tool_output(text: str, *, limit: int = 4000) -> tuple[str, dict[str, Any]]:
    return context_safe_output(text, limit=limit)


def _tool_message_metadata(result_metadata: dict[str, Any], tool_metadata: dict[str, Any]) -> dict[str, Any]:
    merged = dict(tool_metadata)
    for key in (
        "path",
        "line_count",
        "char_count",
        "segmented",
        "segment_index",
        "segment_count",
        "segment_lines",
        "segment_start_line",
        "segment_end_line",
        "next_segment",
        "query",
        "total_matches",
        "offset",
        "limit",
        "returned_matches",
        "next_offset",
        "agent_name",
        "turn_count",
        "tool_count",
        "stop_reason",
        "summary",
        "tool_names",
        "model_name",
        "session_path",
    ):
        if key in result_metadata:
            merged[key] = result_metadata[key]
    return merged
