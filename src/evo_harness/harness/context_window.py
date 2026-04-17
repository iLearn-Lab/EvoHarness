from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from evo_harness.harness.messages import ChatMessage, render_message_text


@dataclass(frozen=True, slots=True)
class ContextWindowPolicy:
    max_messages: int
    max_chars: int
    preserve_recent_messages: int = 4
    summary_max_lines: int = 16
    summary_max_lines_for_unit: int = 8


def prepare_messages_for_provider(
    messages: list[dict[str, Any]],
    *,
    policy: ContextWindowPolicy,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    selected_units = message_units(messages)
    selected = flatten_units(selected_units)
    if len(selected) <= policy.max_messages and messages_char_count(selected) <= policy.max_chars:
        return provider_safe_messages(selected)

    preserve_recent = max(2, min(policy.preserve_recent_messages, max(2, policy.max_messages)))
    compacted_units, compact_payload = compact_message_units_for_context(
        selected_units,
        preserve_recent=preserve_recent,
        summary_max_lines=policy.summary_max_lines,
    )
    selected_units = compacted_units
    selected = flatten_units(selected_units)
    if len(selected) <= policy.max_messages and messages_char_count(selected) <= policy.max_chars:
        return provider_safe_messages(selected, compact_payload)

    truncation_payload: dict[str, Any] | None = compact_payload
    if len(selected) > policy.max_messages:
        before = len(selected)
        selected_units = take_recent_units_by_message_budget(selected_units, max_messages=policy.max_messages)
        selected = flatten_units(selected_units)
        truncation_payload = {
            "reason": "max_context_messages",
            "removed_messages": before - len(selected),
            "kept_messages": len(selected),
            "after_compaction": compact_payload is not None,
        }

    total_chars = messages_char_count(selected)
    if total_chars > policy.max_chars:
        before = len(selected)
        selected_units = take_recent_units_by_char_budget(
            selected_units,
            max_chars=policy.max_chars,
            summary_max_lines=policy.summary_max_lines_for_unit,
        )
        selected = flatten_units(selected_units)
        truncation_payload = {
            "reason": "max_context_chars",
            "removed_messages": before - len(selected),
            "kept_messages": len(selected),
            "kept_chars": messages_char_count(selected),
            "after_compaction": compact_payload is not None,
        }
    return provider_safe_messages(selected, truncation_payload)


def compact_message_units_for_context(
    units: list[list[dict[str, Any]]],
    *,
    preserve_recent: int,
    summary_max_lines: int,
) -> tuple[list[list[dict[str, Any]]], dict[str, Any] | None]:
    if len(units) <= preserve_recent:
        return [list(unit) for unit in units], None

    older_units = units[:-preserve_recent]
    newer_units = units[-preserve_recent:]
    older = flatten_units(older_units)
    summary = summarize_messages(older, max_lines=summary_max_lines)
    if not summary:
        return [list(unit) for unit in newer_units], None

    summary_unit = [
        ChatMessage(
            role="assistant",
            text=f"[conversation summary]\n{summary}",
            metadata={"kind": "conversation_summary"},
        ).to_dict()
    ]
    payload = {
        "reason": "conversation_compacted",
        "removed_messages": len(older),
        "kept_messages": len(flatten_units(newer_units)) + 1,
        "summary_chars": len(summary),
        "preserved_recent_messages": len(flatten_units(newer_units)),
    }
    return [summary_unit, *[list(unit) for unit in newer_units]], payload


def summarize_messages(messages: Iterable[dict[str, Any]], *, max_lines: int = 16) -> str:
    lines: list[str] = []
    for message in messages:
        role = str(message.get("role", "unknown"))
        text = message_window_text(message).strip()
        if not text and role == "tool":
            tool_name = message.get("tool_name") or "tool"
            text = f"{tool_name}: {str(message.get('text', '')).strip()}"
        if not text:
            continue
        lines.append(f"{role}: {text[:240]}")
        if len(lines) >= max_lines:
            break
    return "\n".join(lines)


def messages_char_count(messages: list[dict[str, Any]]) -> int:
    return sum(len(message_window_text(message)) for message in messages)


def message_units(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    units: list[list[dict[str, Any]]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        role = str(message.get("role", ""))
        tool_calls = list(message.get("tool_calls", []) or [])
        if role == "assistant" and tool_calls:
            call_ids = {str(call.get("id", "")) for call in tool_calls if str(call.get("id", ""))}
            unit = [message]
            index += 1
            while index < len(messages):
                candidate = messages[index]
                if str(candidate.get("role", "")) != "tool":
                    break
                metadata = dict(candidate.get("metadata", {}) or {})
                tool_call_id = str(metadata.get("tool_call_id", "") or "")
                if tool_call_id and tool_call_id in call_ids:
                    unit.append(candidate)
                    index += 1
                    continue
                break
            units.append(unit)
            continue
        units.append([message])
        index += 1
    return units


def flatten_units(units: Iterable[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for unit in units:
        flattened.extend(unit)
    return flattened


def take_recent_units_by_message_budget(
    units: list[list[dict[str, Any]]],
    *,
    max_messages: int,
    summary_max_lines: int = 8,
) -> list[list[dict[str, Any]]]:
    kept: list[list[dict[str, Any]]] = []
    running_messages = 0
    for unit in reversed(units):
        unit_count = len(unit)
        if kept and running_messages + unit_count > max_messages:
            break
        if not kept and unit_count > max_messages:
            kept.append([summary_message_for_unit(unit, kind="message_budget_summary", max_lines=summary_max_lines)])
            break
        kept.append(unit)
        running_messages += unit_count
    kept.reverse()
    return kept or [[summary_message_for_unit(flatten_units(units[-1:]), kind="message_budget_summary", max_lines=summary_max_lines)]]


def take_recent_units_by_char_budget(
    units: list[list[dict[str, Any]]],
    *,
    max_chars: int,
    summary_max_lines: int = 8,
) -> list[list[dict[str, Any]]]:
    kept: list[list[dict[str, Any]]] = []
    running_chars = 0
    for unit in reversed(units):
        unit_chars = messages_char_count(unit)
        if kept and running_chars + unit_chars > max_chars:
            break
        if not kept and unit_chars > max_chars:
            kept.append([summary_message_for_unit(unit, kind="char_budget_summary", max_lines=summary_max_lines)])
            break
        kept.append(unit)
        running_chars += unit_chars
    kept.reverse()
    return kept or [[summary_message_for_unit(flatten_units(units[-1:]), kind="char_budget_summary", max_lines=summary_max_lines)]]


def summary_message_for_unit(
    unit: Iterable[dict[str, Any]],
    *,
    kind: str,
    max_lines: int = 8,
) -> dict[str, Any]:
    summary = summarize_messages(list(unit), max_lines=max_lines) or "Recent tool-heavy context was compacted to fit the provider window."
    return ChatMessage(
        role="assistant",
        text=f"[conversation summary]\n{summary}",
        metadata={"kind": kind},
    ).to_dict()


def provider_safe_messages(
    messages: list[dict[str, Any]],
    payload: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    sanitized: list[dict[str, Any]] = []
    dropped_orphans: list[dict[str, Any]] = []
    repaired_assistant_tool_calls = 0
    active_tool_call_ids: set[str] = set()

    for index, message in enumerate(messages):
        role = str(message.get("role", ""))
        if role == "assistant":
            tool_calls = list(message.get("tool_calls", []) or [])
            expected_tool_call_ids = {
                str(call.get("id", ""))
                for call in tool_calls
                if str(call.get("id", ""))
            }
            if expected_tool_call_ids:
                observed_tool_call_ids: set[str] = set()
                cursor = index + 1
                while cursor < len(messages):
                    candidate = messages[cursor]
                    if str(candidate.get("role", "")) != "tool":
                        break
                    metadata = dict(candidate.get("metadata", {}) or {})
                    tool_call_id = str(metadata.get("tool_call_id", "") or "")
                    if tool_call_id:
                        observed_tool_call_ids.add(tool_call_id)
                    cursor += 1
                if not expected_tool_call_ids <= observed_tool_call_ids:
                    text = message_window_text(message).strip()
                    note = (
                        "[compatibility note]\n"
                        "This assistant turn contained tool calls that were interrupted before all tool results were recorded. "
                        "The tool calls were summarized instead of being sent back to the provider as active calls."
                    )
                    repaired = dict(message)
                    repaired["text"] = f"{text}\n\n{note}".strip() if text else note
                    repaired["tool_calls"] = []
                    metadata = dict(repaired.get("metadata", {}) or {})
                    metadata["repaired_incomplete_tool_calls"] = sorted(expected_tool_call_ids - observed_tool_call_ids)
                    repaired["metadata"] = metadata
                    sanitized.append(repaired)
                    repaired_assistant_tool_calls += 1
                    active_tool_call_ids = set()
                    continue
            sanitized.append(message)
            active_tool_call_ids = expected_tool_call_ids
            continue
        if role == "tool":
            metadata = dict(message.get("metadata", {}) or {})
            tool_call_id = str(metadata.get("tool_call_id", "") or "")
            if tool_call_id and tool_call_id in active_tool_call_ids:
                sanitized.append(message)
            else:
                dropped_orphans.append(message)
            continue
        active_tool_call_ids = set()
        sanitized.append(message)

    event_payload = dict(payload or {})
    if dropped_orphans:
        note = ChatMessage(
            role="assistant",
            text=(
                "[compatibility note]\n"
                "Older tool results were compacted to keep the provider request valid."
            ),
            metadata={"kind": "compatibility_note"},
        ).to_dict()
        sanitized = [note, *sanitized] if sanitized else [note]
        event_payload["dropped_orphan_tool_messages"] = len(dropped_orphans)
        if "reason" not in event_payload:
            event_payload["reason"] = "provider_window_sanitized"
    if repaired_assistant_tool_calls:
        event_payload["repaired_incomplete_assistant_tool_calls"] = repaired_assistant_tool_calls
        if "reason" not in event_payload:
            event_payload["reason"] = "provider_window_sanitized"
    return sanitized, (event_payload or None)


def message_window_text(message: dict[str, Any]) -> str:
    return render_message_text(message, include_attachment_paths=True)
