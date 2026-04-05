from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from evo_harness.cli import _build_doctor_report
from evo_harness.execution import promotion_analytics_report, promotion_report
from evo_harness.harness.session import session_analytics_report


PROTOCOL_VERSION = "2025-06-18"


def _workspace_root() -> Path:
    configured = os.environ.get("EVO_HARNESS_WORKSPACE", "").strip()
    if configured:
        return Path(configured).resolve()
    return Path.cwd().resolve()


def _doctor_payload() -> dict[str, Any]:
    return _build_doctor_report(_workspace_root())


def _promotion_payload(*, limit: int = 20) -> dict[str, Any]:
    workspace = _workspace_root()
    return {
        "workspace": str(workspace),
        "report": promotion_report(workspace, limit=limit),
        "analytics": promotion_analytics_report(workspace, limit=limit),
    }


def _session_payload(*, limit: int = 20) -> dict[str, Any]:
    workspace = _workspace_root()
    return {
        "workspace": str(workspace),
        "sessions": session_analytics_report(workspace, limit=limit),
    }


def _resource_payload(uri: str) -> dict[str, Any]:
    if uri == "ops://doctor":
        return _doctor_payload()
    if uri == "ops://promotions":
        return _promotion_payload(limit=20)
    if uri == "ops://sessions":
        return _session_payload(limit=20)
    raise ValueError(f"Unknown resource: {uri}")


def _release_prompt(arguments: dict[str, Any]) -> str:
    target = str(arguments.get("target", "")).strip() or "the current candidate"
    doctor = _doctor_payload()
    counts = doctor["counts"]
    warning_count = len(doctor.get("warnings", []))
    return (
        f"Assess release readiness for {target}.\n"
        f"- Current surface: commands={counts['commands']} skills={counts['skills']} "
        f"agents={counts['agents']} plugins={counts['plugins']} "
        f"mcp_servers={counts['mcp_servers']} mcp_tools={counts['mcp_tools']}\n"
        f"- Doctor warnings: {warning_count}\n"
        "- Review structural gaps, MCP health, validation coverage, and recent session evidence.\n"
        "- End with go/no-go, blockers, and the smallest next safe move."
    )


def _handle_method(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {"name": "quality-gate", "version": "0.1.0"},
            "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
        }
    if method == "tools/list":
        return {
            "tools": [
                {
                    "name": "doctor_report",
                    "description": "Return the Evo Harness doctor report including ecosystem health checks.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
                {
                    "name": "promotion_summary",
                    "description": "Return promotion totals and analytics for the current workspace.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"limit": {"type": "integer"}},
                        "additionalProperties": False,
                    },
                },
                {
                    "name": "session_summary",
                    "description": "Return session analytics for the current workspace.",
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
        if name == "doctor_report":
            payload = _doctor_payload()
        elif name == "promotion_summary":
            payload = _promotion_payload(limit=int(arguments.get("limit", 20)))
        elif name == "session_summary":
            payload = _session_payload(limit=int(arguments.get("limit", 20)))
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
                    "uri": "ops://doctor",
                    "name": "Doctor Report",
                    "mimeType": "application/json",
                    "description": "Doctor report with ecosystem health findings.",
                },
                {
                    "uri": "ops://promotions",
                    "name": "Promotion Summary",
                    "mimeType": "application/json",
                    "description": "Promotion totals and analytics.",
                },
                {
                    "uri": "ops://sessions",
                    "name": "Session Summary",
                    "mimeType": "application/json",
                    "description": "Session analytics report.",
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
                    "name": "release_readiness_brief",
                    "description": "Generate a compact release-readiness review brief.",
                    "arguments": [
                        {
                            "name": "target",
                            "description": "Candidate, branch, or workflow to review.",
                            "required": False,
                        }
                    ],
                }
            ]
        }
    if method == "prompts/get":
        name = str(params.get("name", ""))
        if name != "release_readiness_brief":
            raise ValueError(f"Unknown prompt: {name}")
        arguments = dict(params.get("arguments", {}) or {})
        return {
            "description": "Release readiness brief",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": _release_prompt(arguments)}],
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
