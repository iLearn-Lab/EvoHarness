from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from evo_harness.harness.content_windows import MatchHit, format_match_listing


PROTOCOL_VERSION = "2025-06-18"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _doc_sources() -> dict[str, tuple[str, Path]]:
    root = _repo_root()
    return {
        "docs://readme": ("README", root / "README.md"),
        "docs://claude": ("CLAUDE", root / "CLAUDE.md"),
        "docs://feature-matrix-zh": ("Feature Matrix (zh-CN)", root / "docs" / "feature-matrix.zh-CN.md"),
    }


def _read_text(path: Path) -> str:
    if not path.exists():
        return f"Missing document: {path}"
    return path.read_text(encoding="utf-8", errors="replace")


def _search_docs(query: str, *, offset: int = 0, limit: int = 12) -> tuple[str, dict[str, Any]]:
    lowered = query.strip().lower()
    if not lowered:
        return "Provide a non-empty query.", {"query": query, "total_matches": 0}
    hits: list[MatchHit] = []
    for uri, (label, path) in _doc_sources().items():
        text = _read_text(path)
        for line_number, line in enumerate(text.splitlines(), 1):
            if lowered in line.lower():
                snippet = line.strip()
                if snippet:
                    hits.append(
                        MatchHit(
                            source=f"{label} [{uri}]",
                            line_number=line_number,
                            text=snippet[:220],
                        )
                    )
    return format_match_listing(label="docs search", query=query, hits=hits, offset=offset, limit=limit)


def _prompt_for_gap(arguments: dict[str, Any]) -> str:
    gap = str(arguments.get("gap", "") or arguments.get("issue", "")).strip()
    gap_text = gap or "an unspecified workspace capability gap"
    return (
        "Investigate the following Evo Harness workspace gap and turn it into an action plan:\n"
        f"- Gap: {gap_text}\n"
        "- Inspect commands, skills, agents, plugins, MCP, and validation coverage.\n"
        "- Identify what is missing in the real workspace, not just the examples.\n"
        "- Propose the smallest next patch that improves live operator experience."
    )


def _handle_method(method: str, params: dict[str, Any]) -> dict[str, Any]:
    docs = _doc_sources()
    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {"name": "workspace-docs", "version": "0.1.0"},
            "capabilities": {
                "tools": {},
                "resources": {},
                "prompts": {},
            },
        }
    if method == "tools/list":
        return {
            "tools": [
                {
                    "name": "search_docs",
                    "description": "Search local Evo Harness docs and workspace instructions. Long results are summarized and paginated.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "offset": {"type": "integer"},
                            "limit": {"type": "integer"},
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                }
            ]
        }
    if method == "tools/call":
        name = str(params.get("name", ""))
        arguments = dict(params.get("arguments", {}) or {})
        if name != "search_docs":
            raise ValueError(f"Unknown tool: {name}")
        text, metadata = _search_docs(
            str(arguments.get("query", "")),
            offset=int(arguments.get("offset", 0)),
            limit=int(arguments.get("limit", 12)),
        )
        return {
            "content": [
                {
                    "type": "text",
                    "text": text,
                }
            ],
            "metadata": metadata,
        }
    if method == "resources/list":
        return {
            "resources": [
                {
                    "uri": uri,
                    "name": label,
                    "mimeType": "text/markdown",
                    "description": f"Local document: {label}",
                }
                for uri, (label, _path) in docs.items()
            ]
        }
    if method == "resources/read":
        uri = str(params.get("uri", ""))
        label, path = docs[uri]
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "text/markdown",
                    "text": _read_text(path),
                    "name": label,
                }
            ]
        }
    if method == "prompts/list":
        return {
            "prompts": [
                {
                    "name": "triage_workspace_gap",
                    "description": "Turn a workspace capability gap into a debugging plan.",
                    "arguments": [
                        {
                            "name": "gap",
                            "description": "The missing capability or workflow problem to investigate.",
                            "required": False,
                        }
                    ],
                }
            ]
        }
    if method == "prompts/get":
        name = str(params.get("name", ""))
        if name != "triage_workspace_gap":
            raise ValueError(f"Unknown prompt: {name}")
        arguments = dict(params.get("arguments", {}) or {})
        return {
            "description": "Workspace gap triage prompt",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": _prompt_for_gap(arguments),
                        }
                    ],
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
                _write_message(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32000, "message": str(exc)},
                    }
                )


if __name__ == "__main__":
    main()
