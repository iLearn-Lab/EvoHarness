from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from evo_harness.harness.runtime import HarnessRuntime
from evo_harness.harness.session import session_analytics_report


PROTOCOL_VERSION = "2025-06-18"


def _workspace_root() -> Path:
    configured = os.environ.get("EVO_HARNESS_WORKSPACE", "").strip()
    if configured:
        return Path(configured).resolve()
    return Path.cwd().resolve()


def _runtime() -> HarnessRuntime:
    return HarnessRuntime(_workspace_root())


def _recent_sessions(*, limit: int = 8) -> dict[str, Any]:
    runtime = _runtime()
    sessions = runtime.list_sessions()[:limit]
    return {
        "workspace": str(_workspace_root()),
        "returned": len(sessions),
        "sessions": sessions,
    }


def _pending_approvals() -> dict[str, Any]:
    runtime = _runtime()
    approvals = runtime.list_approvals(status="pending")
    return {
        "workspace": str(_workspace_root()),
        "pending": len(approvals),
        "approvals": approvals,
    }


def _task_board() -> dict[str, Any]:
    runtime = _runtime()
    tasks = runtime.list_tasks()
    return {
        "workspace": str(_workspace_root()),
        "tasks": tasks,
        "count": len(tasks),
    }


def _session_metrics(*, limit: int = 20) -> dict[str, Any]:
    return {
        "workspace": str(_workspace_root()),
        "report": session_analytics_report(_workspace_root(), limit=limit),
    }


def _resource_payload(uri: str) -> dict[str, Any]:
    if uri == "sessions://recent":
        return _recent_sessions(limit=10)
    if uri == "sessions://approvals":
        return _pending_approvals()
    if uri == "sessions://tasks":
        return _task_board()
    raise ValueError(f"Unknown resource: {uri}")


def _stability_prompt(arguments: dict[str, Any]) -> str:
    focus = str(arguments.get("focus", "")).strip() or "recent session stability"
    metrics = _session_metrics(limit=10)["report"]["totals"]
    return (
        f"Review {focus} for the current workspace.\n"
        f"- Recent sessions: {metrics.get('sessions', 0)}\n"
        f"- Average turns: {metrics.get('avg_turns', 0)}\n"
        f"- Average tool calls: {metrics.get('avg_tool_calls', 0)}\n"
        "- Use sessions, pending approvals, and background-task state to explain where flow is slowing down.\n"
        "- End with the smallest workflow improvement worth landing next."
    )


def _handle_method(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {"name": "session-lab", "version": "0.1.0"},
            "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
        }
    if method == "tools/list":
        return {
            "tools": [
                {
                    "name": "recent_sessions",
                    "description": "Return recent archived session summaries.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"limit": {"type": "integer"}},
                        "additionalProperties": False,
                    },
                },
                {
                    "name": "pending_approvals",
                    "description": "Return pending approval requests for the workspace.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
                {
                    "name": "task_board",
                    "description": "Return current background task records for the workspace.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
                {
                    "name": "session_metrics",
                    "description": "Return session analytics totals and recent summaries.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"limit": {"type": "integer"}},
                        "additionalProperties": False,
                    },
                },
            ]
        }
    if method == "tools/call":
        name = str(params.get("name", ""))
        arguments = dict(params.get("arguments", {}) or {})
        if name == "recent_sessions":
            payload = _recent_sessions(limit=int(arguments.get("limit", 8)))
        elif name == "pending_approvals":
            payload = _pending_approvals()
        elif name == "task_board":
            payload = _task_board()
        elif name == "session_metrics":
            payload = _session_metrics(limit=int(arguments.get("limit", 20)))
        else:
            raise ValueError(f"Unknown tool: {name}")
        return {
            "content": [{"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False)}],
            "metadata": {"workspace": str(_workspace_root()), "tool": name},
        }
    if method == "resources/list":
        return {
            "resources": [
                {
                    "uri": "sessions://recent",
                    "name": "Recent Sessions",
                    "mimeType": "application/json",
                    "description": "Recent archived session summaries.",
                },
                {
                    "uri": "sessions://approvals",
                    "name": "Pending Approvals",
                    "mimeType": "application/json",
                    "description": "Pending approval requests for the workspace.",
                },
                {
                    "uri": "sessions://tasks",
                    "name": "Task Board",
                    "mimeType": "application/json",
                    "description": "Current task records for the workspace.",
                },
            ]
        }
    if method == "resources/read":
        uri = str(params.get("uri", ""))
        payload = _resource_payload(uri)
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(payload, indent=2, ensure_ascii=False),
                }
            ]
        }
    if method == "prompts/list":
        return {
            "prompts": [
                {
                    "name": "stability_followup",
                    "description": "Turn recent session evidence into a focused follow-up brief.",
                    "arguments": [
                        {"name": "focus", "description": "Aspect of stability to review", "required": False},
                    ],
                }
            ]
        }
    if method == "prompts/get":
        name = str(params.get("name", ""))
        if name != "stability_followup":
            raise ValueError(f"Unknown prompt: {name}")
        arguments = dict(params.get("arguments", {}) or {})
        return {
            "description": "Session stability follow-up brief",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": _stability_prompt(arguments)}],
                }
            ],
        }
    if method == "notifications/initialized":
        return {}
    raise ValueError(f"Unsupported MCP method: {method}")


def _read_message() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line == b"\r\n":
            break
        key, value = line.decode("ascii").split(":", 1)
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def _write_message(payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    sys.stdout.buffer.write(header + body)
    sys.stdout.buffer.flush()


def main() -> None:
    while True:
        message = _read_message()
        if message is None:
            return
        method = str(message.get("method", ""))
        request_id = message.get("id")
        try:
            result = _handle_method(method, dict(message.get("params", {}) or {}))
            if request_id is not None:
                _write_message({"jsonrpc": "2.0", "id": request_id, "result": result})
        except Exception as exc:
            if request_id is not None:
                _write_message({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}})


if __name__ == "__main__":
    main()
