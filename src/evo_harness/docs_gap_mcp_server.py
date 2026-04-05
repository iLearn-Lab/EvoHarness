from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = "2025-06-18"


def _workspace_root() -> Path:
    configured = os.environ.get("EVO_HARNESS_WORKSPACE", "").strip()
    if configured:
        return Path(configured).resolve()
    return Path.cwd().resolve()


def _doc_paths() -> list[Path]:
    root = _workspace_root()
    seen: set[Path] = set()
    docs: list[Path] = []
    patterns = [
        "README.md",
        "CLAUDE.md",
        "docs/**/*.md",
        "*.md",
    ]
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            docs.append(resolved)
    return docs


def _rel(path: Path) -> str:
    return str(path.relative_to(_workspace_root()))


def _catalog_docs(*, limit: int = 40) -> dict[str, Any]:
    docs = _doc_paths()
    items = [
        {
            "path": _rel(path),
            "name": path.name,
            "size": path.stat().st_size,
        }
        for path in docs[:limit]
    ]
    return {
        "workspace": str(_workspace_root()),
        "total": len(docs),
        "returned": len(items),
        "documents": items,
    }


def _search_doc_text(query: str, *, limit: int = 20) -> dict[str, Any]:
    lowered = query.strip().lower()
    if not lowered:
        return {"query": query, "total": 0, "matches": []}
    matches: list[dict[str, Any]] = []
    for path in _doc_paths():
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), 1):
            if lowered in line.lower():
                matches.append(
                    {
                        "path": _rel(path),
                        "line": line_number,
                        "text": line.strip()[:220],
                    }
                )
                if len(matches) >= limit:
                    return {"query": query, "total": len(matches), "matches": matches}
    return {"query": query, "total": len(matches), "matches": matches}


def _read_doc_excerpt(path_str: str, *, max_chars: int = 4000) -> dict[str, Any]:
    root = _workspace_root()
    path = (root / path_str).resolve()
    if not path.exists():
        raise ValueError(f"Document not found: {path_str}")
    if root not in path.parents and path != root:
        raise ValueError(f"Document must stay inside the workspace: {path_str}")
    text = path.read_text(encoding="utf-8", errors="replace")
    excerpt = text[:max_chars]
    return {
        "path": _rel(path),
        "char_count": len(text),
        "excerpt": excerpt,
        "truncated": len(text) > len(excerpt),
    }


def _resource_payload(uri: str) -> dict[str, Any]:
    if uri == "docs://catalog":
        return _catalog_docs(limit=60)
    if uri == "docs://readme":
        return _read_doc_excerpt("README.md")
    if uri == "docs://claude":
        return _read_doc_excerpt("CLAUDE.md")
    raise ValueError(f"Unknown resource: {uri}")


def _repair_prompt(arguments: dict[str, Any]) -> str:
    target = str(arguments.get("target", "")).strip() or "the current workspace docs"
    focus = str(arguments.get("focus", "")).strip() or "the highest-value documentation gap"
    catalog = _catalog_docs(limit=12)
    return (
        f"Improve documentation for {target}.\n"
        f"- Focus on: {focus}\n"
        f"- Visible docs in workspace: {catalog['total']}\n"
        "- Inspect existing docs before creating new ones.\n"
        "- Prefer changes that improve onboarding, discoverability, or operational clarity.\n"
        "- End with the smallest doc bundle worth editing now."
    )


def _handle_method(method: str, params: dict[str, Any]) -> dict[str, Any]:
    if method == "initialize":
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {"name": "docs-gap", "version": "0.1.0"},
            "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
        }
    if method == "tools/list":
        return {
            "tools": [
                {
                    "name": "catalog_docs",
                    "description": "List visible markdown docs in the current workspace.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "limit": {"type": "integer"},
                        },
                        "additionalProperties": False,
                    },
                },
                {
                    "name": "search_doc_text",
                    "description": "Search markdown docs by text content.",
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
                    "name": "read_doc_excerpt",
                    "description": "Read a compact excerpt from one workspace document.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "max_chars": {"type": "integer"},
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                },
            ]
        }
    if method == "tools/call":
        name = str(params.get("name", ""))
        arguments = dict(params.get("arguments", {}) or {})
        if name == "catalog_docs":
            payload = _catalog_docs(limit=int(arguments.get("limit", 40)))
        elif name == "search_doc_text":
            payload = _search_doc_text(
                str(arguments.get("query", "")),
                limit=int(arguments.get("limit", 20)),
            )
        elif name == "read_doc_excerpt":
            payload = _read_doc_excerpt(
                str(arguments.get("path", "")),
                max_chars=int(arguments.get("max_chars", 4000)),
            )
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
                    "uri": "docs://catalog",
                    "name": "Docs Catalog",
                    "mimeType": "application/json",
                    "description": "Catalog of visible markdown docs in the workspace.",
                },
                {
                    "uri": "docs://readme",
                    "name": "README Excerpt",
                    "mimeType": "application/json",
                    "description": "Compact excerpt from README.md.",
                },
                {
                    "uri": "docs://claude",
                    "name": "CLAUDE Excerpt",
                    "mimeType": "application/json",
                    "description": "Compact excerpt from CLAUDE.md.",
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
                    "name": "documentation_repair_brief",
                    "description": "Turn a documentation gap into a focused repair brief.",
                    "arguments": [
                        {"name": "target", "description": "Workspace or document area", "required": False},
                        {"name": "focus", "description": "Gap to address", "required": False},
                    ],
                }
            ]
        }
    if method == "prompts/get":
        name = str(params.get("name", ""))
        if name != "documentation_repair_brief":
            raise ValueError(f"Unknown prompt: {name}")
        arguments = dict(params.get("arguments", {}) or {})
        return {
            "description": "Documentation repair brief",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": _repair_prompt(arguments)}],
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
