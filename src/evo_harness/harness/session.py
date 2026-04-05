from __future__ import annotations

import json
import time
from collections import Counter
from hashlib import sha1
from pathlib import Path
from typing import Any


def get_session_dir(workspace: str | Path) -> Path:
    root = Path(workspace).resolve()
    digest = sha1(str(root).encode("utf-8")).hexdigest()[:12]
    path = root / ".evo-harness" / "sessions" / f"{root.name}-{digest}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_session_snapshot(
    *,
    workspace: str | Path,
    model: str,
    system_prompt: str,
    messages: list[dict[str, Any]],
    usage: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    session_id: str = "latest",
) -> Path:
    created_at = time.time()
    archive_id = _timestamp_session_id(created_at)
    payload = {
        "session_id": archive_id if session_id == "latest" else session_id,
        "workspace": str(Path(workspace).resolve()),
        "model": model,
        "system_prompt": system_prompt,
        "messages": messages,
        "usage": usage or {},
        "metadata": metadata or {},
        "created_at": created_at,
        "summary": _session_summary(messages, metadata or {}),
        "message_count": len(messages),
    }
    session_dir = get_session_dir(workspace)
    archive_path = session_dir / f"{payload['session_id']}.json"
    archive_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    alias_id = session_id or "latest"
    alias_payload = dict(payload)
    alias_payload["session_id"] = alias_id
    alias_payload["archive_session_id"] = payload["session_id"]
    alias_path = session_dir / f"{alias_id}.json"
    alias_path.write_text(json.dumps(alias_payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return alias_path


def load_session_snapshot(workspace: str | Path, session_id: str = "latest") -> dict[str, Any] | None:
    path = get_session_dir(workspace) / f"{session_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_session_snapshots(workspace: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    snapshots = _load_session_payloads(workspace, include_alias=False)
    if not snapshots:
        snapshots = _load_session_payloads(workspace, include_alias=True)
    snapshots = snapshots[:limit]
    return [
        {
            "session_id": data.get("session_id", ""),
            "created_at": data.get("created_at", 0),
            "summary": data.get("summary") or _session_summary(list(data.get("messages", [])), dict(data.get("metadata", {}))),
            "message_count": data.get("message_count", len(data.get("messages", []))),
            "model": data.get("model", ""),
            "stop_reason": dict(data.get("metadata", {})).get("stop_reason"),
            "turn_count": dict(data.get("metadata", {})).get("turn_count"),
            "tool_calls": dict(data.get("metadata", {})).get("query_stats", {}).get("total_tool_calls"),
            "active_command": dict(dict(data.get("metadata", {})).get("active_command") or {}).get("name"),
        }
        for data in snapshots
    ]


def export_session_markdown(workspace: str | Path, session_id: str = "latest") -> Path:
    snapshot = load_session_snapshot(workspace, session_id)
    if snapshot is None:
        raise FileNotFoundError(f"No session snapshot found for {session_id}")
    path = get_session_dir(workspace) / f"{session_id}.md"
    parts = ["# Evo Harness Session Transcript"]
    for message in snapshot.get("messages", []):
        role = message.get("role", "unknown").capitalize()
        text = message.get("text", "")
        parts.append(f"\n## {role}\n")
        parts.append(text)
    path.write_text("\n".join(parts).strip() + "\n", encoding="utf-8")
    return path


def session_analytics_report(workspace: str | Path, *, limit: int = 50) -> dict[str, Any]:
    payloads = _load_session_payloads(workspace, include_alias=False)
    if not payloads:
        payloads = _load_session_payloads(workspace, include_alias=True)
    payloads = payloads[:limit]
    if not payloads:
        return {
            "totals": {"sessions": 0, "avg_turns": 0.0, "avg_tool_calls": 0.0},
            "by_stop_reason": {},
            "top_tools": [],
            "top_commands": [],
            "recent": [],
        }

    stop_reasons: Counter[str] = Counter()
    top_tools: Counter[str] = Counter()
    top_commands: Counter[str] = Counter()
    total_turns = 0
    total_tool_calls = 0
    total_mutating_calls = 0
    total_failures = 0
    recent: list[dict[str, Any]] = []

    for payload in payloads:
        metadata = dict(payload.get("metadata", {}))
        query_stats = dict(metadata.get("query_stats", {}))
        tool_history = list(metadata.get("tool_history", []))
        active_command = metadata.get("active_command") or {}
        stop_reason = str(metadata.get("stop_reason", "unknown"))
        stop_reasons[stop_reason] += 1
        total_turns += int(metadata.get("turn_count", 0) or 0)
        total_tool_calls += int(query_stats.get("total_tool_calls", len(tool_history)) or 0)
        total_mutating_calls += int(query_stats.get("mutating_tool_calls", 0) or 0)
        for record in tool_history:
            top_tools[str(record.get("tool_name", "unknown"))] += 1
            if dict(record.get("result", {})).get("is_error"):
                total_failures += 1
        if active_command.get("name"):
            top_commands[str(active_command["name"])] += 1
        recent.append(
            {
                "session_id": payload.get("session_id"),
                "created_at": payload.get("created_at"),
                "stop_reason": stop_reason,
                "turn_count": metadata.get("turn_count"),
                "tool_calls": query_stats.get("total_tool_calls", len(tool_history)),
                "active_command": active_command.get("name"),
            }
        )

    session_count = len(payloads)
    return {
        "totals": {
            "sessions": session_count,
            "avg_turns": round(total_turns / session_count, 2),
            "avg_tool_calls": round(total_tool_calls / session_count, 2),
            "avg_mutating_tool_calls": round(total_mutating_calls / session_count, 2),
            "total_tool_failures": total_failures,
        },
        "by_stop_reason": dict(stop_reasons.most_common()),
        "top_tools": [{"name": name, "count": count} for name, count in top_tools.most_common(10)],
        "top_commands": [{"name": name, "count": count} for name, count in top_commands.most_common(10)],
        "recent": recent[:10],
    }


def _load_session_payloads(workspace: str | Path, *, include_alias: bool) -> list[dict[str, Any]]:
    session_dir = get_session_dir(workspace)
    payloads: list[dict[str, Any]] = []
    for path in sorted(session_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        if not include_alias and (path.stem == "latest" or path.name.endswith(".rollback.json")):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        payloads.append(data)
    return payloads


def _timestamp_session_id(created_at: float) -> str:
    millis = int((created_at - int(created_at)) * 1000)
    return f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(created_at))}-{millis:03d}"


def _session_summary(messages: list[dict[str, Any]], metadata: dict[str, Any]) -> str:
    for role in ("user", "assistant"):
        for message in messages:
            if message.get("role") == role and str(message.get("text", "")).strip():
                return str(message["text"]).strip()[:120]
    active_command = dict(metadata.get("active_command") or {})
    if active_command.get("name"):
        return f"Session under command {active_command['name']}"
    return "Saved session"
