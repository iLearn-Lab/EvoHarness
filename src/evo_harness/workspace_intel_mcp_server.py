from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from evo_harness.harness.runtime import HarnessRuntime
from evo_harness.harness.session import list_session_snapshots


PROTOCOL_VERSION = "2025-06-18"


def _workspace_root() -> Path:
    configured = os.environ.get("EVO_HARNESS_WORKSPACE", "").strip()
    if configured:
        return Path(configured).resolve()
    return Path.cwd().resolve()


def _runtime() -> HarnessRuntime:
    return HarnessRuntime(_workspace_root())


def _snapshot(*, include_names: bool = False) -> dict[str, Any]:
    runtime = _runtime()
    commands = runtime.list_commands()
    agents = runtime.list_agents()
    skills = runtime.list_skills()
    plugins = runtime.list_plugins()
    mcp_servers = runtime.list_mcp_servers()
    payload: dict[str, Any] = {
        "workspace": str(_workspace_root()),
        "counts": {
            "tools": len(runtime.list_tools()),
            "commands": len(commands),
            "agents": len(agents),
            "skills": len(skills),
            "plugins": len(plugins),
            "mcp_servers": len(mcp_servers),
            "mcp_tools": len(runtime.list_mcp_tools()),
            "mcp_resources": len(runtime.list_mcp_resources()),
            "mcp_prompts": len(runtime.list_mcp_prompts()),
            "tasks": len(runtime.list_tasks()),
            "sessions": len(runtime.list_sessions()),
            "pending_approvals": len(runtime.list_approvals(status="pending")),
        },
    }
    if include_names:
        payload["names"] = {
            "commands": [item["name"] for item in commands],
            "agents": [item["name"] for item in agents],
            "skills": [item["name"] for item in skills],
            "plugins": [item["manifest"]["name"] for item in plugins],
            "mcp_servers": [item["name"] for item in mcp_servers],
        }
    return payload


def _search_surface(query: str, *, limit: int = 12) -> dict[str, Any]:
    runtime = _runtime()
    lowered = query.strip().lower()
    items: list[dict[str, str]] = []
    if not lowered:
        return {"query": query, "results": [], "total": 0}

    for command in runtime.list_commands():
        items.append(
            {
                "kind": "command",
                "name": str(command.get("name", "")),
                "description": str(command.get("description", "")),
                "source": str(command.get("source", "")),
                "path": str(command.get("path", "")),
            }
        )
    for agent in runtime.list_agents():
        items.append(
            {
                "kind": "agent",
                "name": str(agent.get("name", "")),
                "description": str(agent.get("description", "")),
                "source": str(agent.get("source", "")),
                "path": str(agent.get("path", "")),
            }
        )
    for skill in runtime.list_skills():
        items.append(
            {
                "kind": "skill",
                "name": str(skill.get("name", "")),
                "description": str(skill.get("description", "")),
                "source": str(skill.get("source", "")),
                "path": str(skill.get("path", "")),
            }
        )
    for plugin in runtime.list_plugins():
        manifest = dict(plugin.get("manifest", {}))
        items.append(
            {
                "kind": "plugin",
                "name": str(manifest.get("name", "")),
                "description": str(manifest.get("description", "")),
                "source": str(plugin.get("source", "")),
                "path": str(plugin.get("path", "")),
            }
        )
    for server in runtime.list_mcp_servers():
        items.append(
            {
                "kind": "mcp_server",
                "name": str(server.get("name", "")),
                "description": str(server.get("description", "")),
                "source": str(server.get("source", "")),
                "path": str(server.get("command") or server.get("url") or ""),
            }
        )

    matches = [
        item
        for item in items
        if lowered in json.dumps(item, ensure_ascii=False).lower()
    ]
    return {
        "query": query,
        "results": matches[:limit],
        "total": len(matches),
        "returned": min(len(matches), limit),
    }


def _recent_sessions(*, limit: int = 5) -> dict[str, Any]:
    sessions = list_session_snapshots(_workspace_root(), limit=limit)
    return {
        "workspace": str(_workspace_root()),
        "sessions": sessions,
        "returned": len(sessions),
    }


def _resource_payload(uri: str) -> dict[str, Any]:
    if uri == "workspace://summary":
        return _snapshot(include_names=False)
    if uri == "workspace://surface":
        return _snapshot(include_names=True)
    if uri == "workspace://sessions":
        return _recent_sessions(limit=8)
    raise ValueError(f"Unknown resource: {uri}")


def _prompt_for_upgrade(arguments: dict[str, Any]) -> str:
    focus = str(arguments.get("focus", "")).strip() or "the current workspace"
    gap = str(arguments.get("gap", "")).strip() or "the next highest-leverage ecosystem gap"
    snapshot = _snapshot(include_names=False)
    counts = snapshot["counts"]
    return (
        f"Plan an ecosystem upgrade for {focus}.\n"
        f"- Investigate: {gap}\n"
        f"- Current counts: commands={counts['commands']} skills={counts['skills']} "
        f"agents={counts['agents']} plugins={counts['plugins']} "
        f"mcp_servers={counts['mcp_servers']} mcp_tools={counts['mcp_tools']}\n"
        "- Prefer additions that are immediately usable, not placeholder assets.\n"
        "- Call out the smallest bundle of skills, agents, commands, plugins, or MCP changes worth shipping next."
    )


def _handle_method(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {"name": "workspace-intel", "version": "0.1.0"},
            "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
        }
    if method == "tools/list":
        return {
            "tools": [
                {
                    "name": "workspace_snapshot",
                    "description": "Return workspace counts and optionally the discovered asset names.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "include_names": {"type": "boolean"},
                        },
                        "additionalProperties": False,
                    },
                },
                {
                    "name": "search_surface",
                    "description": "Search commands, skills, agents, plugins, and MCP servers by keyword.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {"type": "integer"},
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                },
                {
                    "name": "recent_sessions",
                    "description": "Return recent archived session summaries for the current workspace.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer"},
                        },
                        "additionalProperties": False,
                    },
                },
            ]
        }
    if method == "tools/call":
        name = str(params.get("name", ""))
        arguments = dict(params.get("arguments", {}) or {})
        if name == "workspace_snapshot":
            payload = _snapshot(include_names=bool(arguments.get("include_names", False)))
        elif name == "search_surface":
            payload = _search_surface(
                str(arguments.get("query", "")),
                limit=int(arguments.get("limit", 12)),
            )
        elif name == "recent_sessions":
            payload = _recent_sessions(limit=int(arguments.get("limit", 5)))
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
                    "uri": "workspace://summary",
                    "name": "Workspace Summary",
                    "mimeType": "application/json",
                    "description": "Counts for the current workspace surface.",
                },
                {
                    "uri": "workspace://surface",
                    "name": "Workspace Surface",
                    "mimeType": "application/json",
                    "description": "Counts plus discovered names across the ecosystem.",
                },
                {
                    "uri": "workspace://sessions",
                    "name": "Recent Sessions",
                    "mimeType": "application/json",
                    "description": "Recent archived session summaries.",
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
                    "name": "plan_ecosystem_upgrade",
                    "description": "Turn current workspace counts and a stated gap into a concrete upgrade plan.",
                    "arguments": [
                        {"name": "focus", "description": "Area or workspace to improve", "required": False},
                        {"name": "gap", "description": "Missing capability to address", "required": False},
                    ],
                }
            ]
        }
    if method == "prompts/get":
        name = str(params.get("name", ""))
        if name != "plan_ecosystem_upgrade":
            raise ValueError(f"Unknown prompt: {name}")
        arguments = dict(params.get("arguments", {}) or {})
        return {
            "description": "Workspace ecosystem upgrade brief",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": _prompt_for_upgrade(arguments)}],
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
