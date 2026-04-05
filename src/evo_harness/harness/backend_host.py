from __future__ import annotations

import contextlib
import json
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from evo_harness.harness.conversation import ConversationEngine
from evo_harness.harness.provider import ScriptedProvider, build_live_provider
from evo_harness.harness.runtime import HarnessRuntime
from evo_harness.harness.session import list_session_snapshots
from evo_harness.harness.slash_commands import (
    SlashCommandContext,
    create_default_slash_command_registry,
)

PROTOCOL_PREFIX = "EVOJSON:"


@dataclass(slots=True)
class BackendHostConfig:
    workspace: str
    settings_path: str | None = None
    provider_script: str | None = None
    resume: str | None = None


class ReactBackendHost:
    def __init__(self, config: BackendHostConfig) -> None:
        self.config = config
        self.runtime = HarnessRuntime(config.workspace, settings_path=config.settings_path)
        self.engine = ConversationEngine(self.runtime)
        if config.resume and config.resume.lower() != "none":
            self.engine.load_session(config.resume)
        self.registry = create_default_slash_command_registry()
        self._write_lock = threading.Lock()
        self._running = True
        self.runtime.approval_prompt = self._ask_permission

    def run(self) -> int:
        self._emit_ready()
        try:
            while self._running:
                request = self._read_request()
                if request is None:
                    self._emit({"type": "shutdown"})
                    break
                request_type = str(request.get("type", ""))
                if request_type == "shutdown":
                    self._emit({"type": "shutdown"})
                    break
                if request_type == "list_sessions":
                    self._emit_select_request()
                    continue
                if request_type != "submit_line":
                    self._emit({"type": "error", "message": f"Unknown request type: {request_type}"})
                    continue
                line = str(request.get("line", "")).strip()
                if not line:
                    continue
                keep_running = self._handle_line(line)
                if not keep_running:
                    self._emit({"type": "shutdown"})
                    break
            return 0
        finally:
            self._shutdown_io()

    def _read_request(self) -> dict[str, object] | None:
        while self._running:
            try:
                raw = sys.stdin.buffer.readline()
            except Exception:
                return {"type": "shutdown"}
            if not raw:
                return None
            payload = raw.decode("utf-8", errors="replace").strip()
            if not payload:
                continue
            try:
                return dict(json.loads(payload))
            except json.JSONDecodeError as exc:
                self._emit({"type": "error", "message": f"Invalid request JSON: {exc}"})
        return None

    def _emit_ready(self) -> None:
        self._emit(
            {
                "type": "ready",
                "state": self._state_payload(),
                "tasks": self._tasks_payload(),
                "commands": self._command_list(),
            }
        )

    def _handle_line(self, line: str) -> bool:
        self._emit({"type": "transcript_item", "item": {"role": "user", "text": line}})
        if line.startswith("/"):
            result = self.registry.dispatch(
                line,
                SlashCommandContext(runtime=self.runtime, engine=self.engine, prompt_fn=self._ask_question),
            )
            if result is None:
                self._emit({"type": "error", "message": f"Unknown command: {line}"})
                self._emit({"type": "line_complete"})
                return True
            if result.clear_screen:
                self._emit({"type": "clear_transcript"})
            if result.message:
                self._emit({"type": "transcript_item", "item": {"role": "system", "text": result.message}})
            self._emit_snapshots()
            self._emit({"type": "line_complete"})
            return not result.should_exit

        try:
            provider = self._active_provider()
        except Exception as exc:
            self._emit(
                {
                    "type": "transcript_item",
                    "item": {
                        "role": "system",
                        "text": (
                            f"Provider setup failed: {exc}\n"
                            "Use /setup for guided configuration, or /login to save an API key."
                        ),
                    },
                }
            )
            self._emit_snapshots()
            self._emit({"type": "line_complete"})
            return True
        try:
            for event in self.engine.submit_stream(prompt=line, provider=provider):
                event_name = event.__class__.__name__
                if event_name == "AssistantTextDelta":
                    self._emit({"type": "assistant_delta", "message": event.text})
                elif event_name == "AssistantTurnComplete":
                    message = dict(getattr(event, "message", {}) or {})
                    text = str(message.get("text", "")).strip()
                    self._emit(
                        {
                            "type": "assistant_complete",
                            "message": text,
                            "item": {"role": "assistant", "text": text},
                        }
                    )
                elif event_name == "ToolExecutionStarted":
                    self._emit(
                        {
                            "type": "tool_started",
                            "tool_name": event.tool_name,
                            "item": {
                                "role": "tool",
                                "text": self._tool_summary(event.tool_name, event.tool_input),
                                "tool_name": event.tool_name,
                                "tool_input": event.tool_input,
                            },
                        }
                    )
                elif event_name == "ToolExecutionCompleted":
                    self._emit(
                        {
                            "type": "tool_completed",
                            "tool_name": event.tool_name,
                            "output": event.output,
                            "is_error": event.is_error,
                            "metadata": event.metadata,
                            "item": {
                                "role": "tool_result",
                                "text": event.output,
                                "tool_name": event.tool_name,
                                "is_error": event.is_error,
                                "metadata": event.metadata,
                            },
                        }
                    )
        except Exception as exc:
            self._emit(
                {
                    "type": "transcript_item",
                    "item": {
                        "role": "system",
                        "text": f"Request failed: {exc}",
                    },
                }
            )
        self._emit_snapshots()
        self._emit({"type": "line_complete"})
        return True

    def _emit_snapshots(self) -> None:
        self._emit({"type": "state_snapshot", "state": self._state_payload()})
        self._emit({"type": "tasks_snapshot", "tasks": self._tasks_payload()})

    def _state_payload(self) -> dict[str, object]:
        profile = self.runtime.settings.provider.profile or self.runtime.settings.provider.provider
        query_result = self.runtime.last_query_result
        usage = getattr(query_result, "usage", {}) if query_result is not None else {}
        return {
            "model": self.runtime.settings.model,
            "cwd": str(self.runtime.workspace),
            "provider": profile,
            "permission_mode": self.runtime.settings.permission.mode,
            "input_tokens": int(usage.get("input_tokens", 0) or 0),
            "output_tokens": int(usage.get("output_tokens", 0) or 0),
            "mcp_connected": len(self.runtime.list_mcp_servers()),
            "pending_approvals": len(self.runtime.list_approvals(status="pending")),
            "command_count": len(self.runtime.list_commands()),
            "skill_count": len(self.runtime.list_skills()),
            "agent_count": len(self.runtime.list_agents()),
            "plugin_count": len(self.runtime.list_plugins()),
            "mcp_server_count": len(self.runtime.list_mcp_servers()),
            "mcp_tool_count": len(self.runtime.list_mcp_tools()),
            "session_count": len(self.runtime.list_sessions()),
            "active_command": self.runtime.active_command.name if self.runtime.active_command else None,
        }

    def _tasks_payload(self) -> list[dict[str, object]]:
        return self.runtime.list_tasks()

    def _command_list(self) -> list[str]:
        slash_commands = [f"/{name}" for name in self.registry.visible_names()]
        workspace_commands = [f"/{item.get('name')}" for item in self.runtime.list_commands() if item.get("name")]
        return [*slash_commands, *workspace_commands]

    def _emit_select_request(self) -> None:
        sessions = list_session_snapshots(self.runtime.workspace, limit=10)
        options = []
        for item in sessions:
            label = f"{item.get('session_id')}  {item.get('message_count')}msg  {item.get('summary') or '(no summary)'}"
            options.append({"value": item.get("session_id"), "label": label})
        self._emit(
            {
                "type": "select_request",
                "modal": {"kind": "select", "title": "Resume Session", "submit_prefix": "/resume "},
                "select_options": options,
            }
        )

    def _emit(self, payload: dict[str, object]) -> None:
        with self._write_lock:
            sys.stdout.write(PROTOCOL_PREFIX + json.dumps(payload, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    def _active_provider(self):
        if self.config.provider_script:
            return ScriptedProvider.from_file(self.config.provider_script)
        return build_live_provider(settings=self.runtime.settings)

    def _ask_permission(self, request) -> bool:
        request_id = uuid4().hex
        self._emit(
            {
                "type": "modal_request",
                "modal": {
                    "kind": "permission",
                    "request_id": request_id,
                    "tool_name": request.tool_name,
                    "reason": request.reason,
                    "file_path": request.file_path,
                    "command": request.command,
                },
            }
        )
        while self._running:
            response = self._read_request()
            if response is None:
                self._running = False
                return False
            request_type = str(response.get("type", ""))
            if request_type == "shutdown":
                self._running = False
                return False
            if request_type != "permission_response":
                continue
            if str(response.get("request_id", "")) != request_id:
                continue
            return bool(response.get("allowed", False))
        return False

    def _ask_question(self, question: str) -> str:
        request_id = uuid4().hex
        self._emit(
            {
                "type": "modal_request",
                "modal": {
                    "kind": "question",
                    "request_id": request_id,
                    "question": question,
                },
            }
        )
        while self._running:
            response = self._read_request()
            if response is None:
                self._running = False
                return ""
            request_type = str(response.get("type", ""))
            if request_type == "shutdown":
                self._running = False
                return ""
            if request_type != "question_response":
                continue
            if str(response.get("request_id", "")) != request_id:
                continue
            return str(response.get("answer", ""))
        return ""

    def _tool_summary(self, tool_name: str, tool_input: dict[str, object] | None) -> str:
        if not tool_input:
            return tool_name
        if tool_name == "run_subagent":
            name = str(tool_input.get("name", "agent"))
            task = str(tool_input.get("task", "")).strip()
            return f"{tool_name} {name}: {task[:80]}"
        if "path" in tool_input:
            segment = tool_input.get("segment")
            if segment is not None:
                return f"{tool_name} {tool_input['path']} segment={segment}"
            return f"{tool_name} {tool_input['path']}"
        if "command" in tool_input:
            return f"{tool_name} {str(tool_input['command'])[:120]}"
        if "pattern" in tool_input:
            offset = tool_input.get("offset")
            suffix = f" offset={offset}" if offset is not None else ""
            return f"{tool_name} {tool_input['pattern']}{suffix}"
        key, value = next(iter(tool_input.items()))
        return f"{tool_name} {key}={str(value)[:80]}"

    def _shutdown_io(self) -> None:
        self._running = False
        with contextlib.suppress(Exception):
            sys.stdin.close()


def run_backend_host(
    *,
    workspace: str,
    settings_path: str | None = None,
    provider_script: str | None = None,
    resume: str | None = None,
) -> int:
    host = ReactBackendHost(
        BackendHostConfig(
            workspace=workspace,
            settings_path=settings_path,
            provider_script=provider_script,
            resume=resume,
        )
    )
    return host.run()


__all__ = ["PROTOCOL_PREFIX", "BackendHostConfig", "ReactBackendHost", "run_backend_host"]
