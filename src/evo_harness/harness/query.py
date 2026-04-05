from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Iterable

from evo_harness.harness.messages import ChatMessage
from evo_harness.harness.provider import BaseProvider
from evo_harness.harness.runtime import HarnessRuntime, RuntimeEvent
from evo_harness.harness.session import save_session_snapshot
from evo_harness.harness.stream_events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ToolExecutionCompleted,
    ToolExecutionStarted,
)


@dataclass
class QueryRunResult:
    events: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    session_path: str
    provider_name: str
    usage: dict[str, int]
    query_stats: dict[str, Any] = field(default_factory=dict)
    stop_reason: str | None = None
    turn_count: int = 0


def run_query(
    runtime: HarnessRuntime,
    *,
    prompt: str,
    provider: BaseProvider,
    command_name: str | None = None,
    command_arguments: str = "",
    max_turns: int = 8,
) -> QueryRunResult:
    runner = _QueryRunner(
        runtime,
        prompt=prompt,
        provider=provider,
        command_name=command_name,
        command_arguments=command_arguments,
        max_turns=max_turns,
    )
    return runner.run()


def run_query_stream(
    runtime: HarnessRuntime,
    *,
    prompt: str,
    provider: BaseProvider,
    command_name: str | None = None,
    command_arguments: str = "",
    max_turns: int = 8,
):
    runner = _QueryRunner(
        runtime,
        prompt=prompt,
        provider=provider,
        command_name=command_name,
        command_arguments=command_arguments,
        max_turns=max_turns,
    )
    yield from runner.run_stream()


class _QueryRunner:
    def __init__(
        self,
        runtime: HarnessRuntime,
        *,
        prompt: str,
        provider: BaseProvider,
        command_name: str | None,
        command_arguments: str,
        max_turns: int,
    ) -> None:
        self.runtime = runtime
        self.prompt = prompt
        self.provider = provider
        self.command_name = command_name
        self.command_arguments = command_arguments
        self.query_settings = runtime.settings.query
        self.system_prompt = runtime.system_prompt(latest_user_prompt=prompt)
        self.effective_max_turns = min(
            max_turns,
            self.query_settings.max_turns,
            runtime.settings.provider.max_turns,
        )
        self.max_consecutive_tool_rounds = min(
            self.query_settings.max_consecutive_tool_rounds,
            runtime.settings.provider.max_consecutive_tool_rounds,
        )
        self.max_repeated_tool_call_signatures = min(
            self.query_settings.max_repeated_tool_call_signatures,
            runtime.settings.provider.max_repeated_tool_call_signatures,
        )
        self.max_empty_assistant_turns = min(
            self.query_settings.max_empty_assistant_turns,
            runtime.settings.provider.max_empty_assistant_turns,
        )
        self.events: list[RuntimeEvent] = []
        self.usage_totals = {"input_tokens": 0, "output_tokens": 0}
        self.query_stats = {
            "total_tool_calls": 0,
            "tool_failures": 0,
            "mutating_tool_calls": 0,
            "mutating_tool_failures": 0,
            "context_truncations": 0,
            "context_compactions": 0,
            "forced_synthesis_turns": 0,
        }
        self.final_stop_reason: str | None = None
        self.turn_count = 0
        self.consecutive_tool_rounds = 0
        self.empty_assistant_turns = 0
        self.repeated_assistant_turns = 0
        self.last_nonempty_assistant_text = ""
        self.tool_signature_counts: dict[str, int] = {}
        self._started = False

    def run(self) -> QueryRunResult:
        self._start()
        try:
            for turn_index in range(self.effective_max_turns):
                turn = self._next_turn(turn_index)
                self._record_assistant_turn(turn, turn_index)
                self._execute_tool_calls(turn.tool_calls)
                if self._should_stop_after_turn(turn):
                    break
            else:
                self.final_stop_reason = self.final_stop_reason or "max_turns"
                self.events.append(RuntimeEvent(kind="query_stopped", payload={"reason": self.final_stop_reason}))
        finally:
            result = self._finish()
        return result

    def run_stream(self):
        self._start()
        try:
            for turn_index in range(self.effective_max_turns):
                turn = self._next_turn(turn_index)
                for event in self._assistant_stream_events(turn, turn_index):
                    yield event
                for event in self._execute_tool_calls(turn.tool_calls, emit_stream=True):
                    yield event
                if self._should_stop_after_turn(turn):
                    break
            else:
                self.final_stop_reason = self.final_stop_reason or "max_turns"
                self.events.append(RuntimeEvent(kind="query_stopped", payload={"reason": self.final_stop_reason}))
        finally:
            self._finish()

    def _start(self) -> None:
        if self._started:
            return
        if self.command_name is not None:
            rendered = self.runtime.set_active_command(self.command_name, self.command_arguments)
            command_message = ChatMessage(role="assistant", text=rendered, metadata={"kind": "command"})
            self.runtime.append_message(command_message)
            self.events.append(RuntimeEvent(kind="command_rendered", payload={"name": self.command_name, "text": rendered}))

        self.runtime.current_provider_factory = lambda: _clone_provider(self.provider)
        self.runtime.last_query_result = None
        self.runtime.hook_executor.execute(
            "SessionStart",
            {"prompt": self.prompt, "provider": self.provider.name},
            cwd=self.runtime.workspace,
        )
        self.runtime.messages.append(ChatMessage(role="user", text=self.prompt).to_dict())
        self.events.append(RuntimeEvent(kind="user_message", payload={"text": self.prompt}))
        self._started = True

    def _next_turn(self, turn_index: int):
        self.turn_count += 1
        provider_messages, window_event = _messages_for_provider(
            self.runtime.messages,
            max_messages=self.query_settings.max_context_messages,
            max_chars=self.query_settings.max_context_chars,
        )
        if window_event is not None:
            if window_event["reason"] == "conversation_compacted":
                self.query_stats["context_compactions"] += 1
                self.events.append(RuntimeEvent(kind="context_window_compacted", payload=window_event))
            else:
                self.query_stats["context_truncations"] += 1
                self.events.append(RuntimeEvent(kind="context_window_trimmed", payload=window_event))

        provider_messages, tool_schema, steering_payload = self._prepare_turn_inputs(
            turn_index,
            provider_messages,
        )
        if steering_payload is not None:
            self.query_stats["forced_synthesis_turns"] += 1
            self.events.append(RuntimeEvent(kind="query_steered", payload=steering_payload))

        turn = self.provider.next_turn(
            system_prompt=self.system_prompt,
            messages=[ChatMessage(**message) for message in provider_messages],
            tool_schema=tool_schema,
        )
        if steering_payload is not None and turn.tool_calls:
            turn.tool_calls = []
            turn.metadata = {
                **dict(turn.metadata or {}),
                "forced_synthesis": True,
                "steering_reason": steering_payload["reason"],
            }
        turn_usage = turn.metadata.get("usage", {}) if turn.metadata else {}
        self.usage_totals["input_tokens"] += int(turn_usage.get("input_tokens", 0) or 0)
        self.usage_totals["output_tokens"] += int(turn_usage.get("output_tokens", 0) or 0)
        if turn.metadata and turn.metadata.get("stop_reason"):
            self.final_stop_reason = str(turn.metadata.get("stop_reason"))
        return turn

    def _prepare_turn_inputs(
        self,
        turn_index: int,
        provider_messages: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
        tool_schema = self.runtime.available_tools()
        steering_reason: str | None = None
        if self.empty_assistant_turns >= self.max_empty_assistant_turns and self.consecutive_tool_rounds > 0:
            steering_reason = "max_empty_assistant_turns"
        elif self.consecutive_tool_rounds >= self.max_consecutive_tool_rounds:
            steering_reason = "max_consecutive_tool_rounds"
        elif turn_index >= self.effective_max_turns - 1 and self.consecutive_tool_rounds > 0:
            steering_reason = "last_turn_force_summary"

        if steering_reason is None:
            return provider_messages, tool_schema, None

        steering_message = ChatMessage(
            role="user",
            text=_build_synthesis_instruction(
                prompt=self.prompt,
                messages=self.runtime.messages,
                tool_history=self.runtime.tool_history,
                reason=steering_reason,
            ),
            metadata={"kind": "query_steering"},
        ).to_dict()
        return (
            [*provider_messages, steering_message],
            [],
            {
                "reason": steering_reason,
                "turn": turn_index + 1,
                "consecutive_tool_rounds": self.consecutive_tool_rounds,
                "tool_calls_so_far": self.query_stats["total_tool_calls"],
            },
        )

    def _record_assistant_turn(self, turn, turn_index: int) -> None:
        if turn.assistant_text or turn.tool_calls:
            if turn.assistant_text.strip():
                self.empty_assistant_turns = 0
                if turn.assistant_text.strip() == self.last_nonempty_assistant_text:
                    self.repeated_assistant_turns += 1
                else:
                    self.repeated_assistant_turns = 0
                self.last_nonempty_assistant_text = turn.assistant_text.strip()
            else:
                self.empty_assistant_turns += 1
            assistant = ChatMessage(
                role="assistant",
                text=turn.assistant_text,
                tool_calls=[call.to_dict() for call in turn.tool_calls],
                metadata=turn.metadata,
            )
            self.runtime.messages.append(assistant.to_dict())
            self.events.append(
                RuntimeEvent(
                    kind="assistant_message",
                    payload={"turn": turn_index + 1, **assistant.to_dict()},
                )
            )
        else:
            self.empty_assistant_turns += 1

    def _assistant_stream_events(self, turn, turn_index: int) -> list[object]:
        self._record_assistant_turn(turn, turn_index)
        events: list[object] = []
        if turn.assistant_text:
            for chunk in _chunk_text(turn.assistant_text, chunk_size=120):
                events.append(AssistantTextDelta(text=chunk))
        payload = self.events[-1].payload if self.events and self.events[-1].kind == "assistant_message" else {"text": turn.assistant_text}
        events.append(
            AssistantTurnComplete(
                message=payload,
                usage=dict(self.usage_totals),
                stop_reason=self.final_stop_reason,
            )
        )
        return events

    def _execute_tool_calls(self, tool_calls, *, emit_stream: bool = False) -> list[object]:
        stream_events: list[object] = []
        if not tool_calls:
            return stream_events

        states = [
            {
                "call": tool_call,
                "is_mutating": _is_mutating_tool(self.runtime, tool_call.name, tool_call.arguments),
                "parallel_safe": _is_parallel_safe_tool(self.runtime, tool_call.name),
            }
            for tool_call in tool_calls
        ]
        for state in states:
            if state["is_mutating"]:
                self.query_stats["mutating_tool_calls"] += 1

        can_parallelize = (
            len(states) > 1
            and self.query_settings.max_parallel_tool_calls > 1
            and all(not state["is_mutating"] for state in states)
            and all(state["parallel_safe"] for state in states)
        )
        if can_parallelize:
            stream_events.extend(self._execute_tool_calls_parallel(states, emit_stream=emit_stream))
        else:
            stream_events.extend(self._execute_tool_calls_sequential(states, emit_stream=emit_stream))
        return stream_events

    def _execute_tool_calls_sequential(self, states, *, emit_stream: bool) -> list[object]:
        stream_events: list[object] = []
        for state in states:
            tool_call = state["call"]
            if emit_stream:
                stream_events.append(
                    ToolExecutionStarted(
                        tool_name=tool_call.name,
                        tool_input=dict(tool_call.arguments),
                        tool_call_id=tool_call.id,
                    )
                )
            result = self.runtime.execute_tool(
                tool_call.name,
                tool_call.arguments,
                tool_call_id=tool_call.id,
            )
            self._record_tool_result(tool_call, result, is_mutating=state["is_mutating"])
            if emit_stream:
                stream_events.append(
                    ToolExecutionCompleted(
                        tool_name=tool_call.name,
                        output=str(result.output),
                        is_error=bool(result.is_error),
                        tool_call_id=tool_call.id,
                        metadata=dict(result.metadata),
                    )
                )
            if self._tool_limits_exceeded():
                break
        return stream_events

    def _execute_tool_calls_parallel(self, states, *, emit_stream: bool) -> list[object]:
        stream_events: list[object] = []
        if emit_stream:
            for state in states:
                tool_call = state["call"]
                stream_events.append(
                    ToolExecutionStarted(
                        tool_name=tool_call.name,
                        tool_input=dict(tool_call.arguments),
                        tool_call_id=tool_call.id,
                    )
                )

        max_workers = min(self.query_settings.max_parallel_tool_calls, len(states))
        finished: dict[int, tuple[Any, Any]] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {}
            for index, state in enumerate(states):
                tool_call = state["call"]
                subruntime = self.runtime.create_subruntime(tool_allowlist=[tool_call.name])
                future = executor.submit(
                    subruntime.execute_tool,
                    tool_call.name,
                    dict(tool_call.arguments),
                    tool_call_id=tool_call.id,
                )
                future_map[future] = (index, state, subruntime)

            for future in as_completed(future_map):
                index, state, _subruntime = future_map[future]
                result = future.result()
                finished[index] = (state, result)
                if emit_stream:
                    tool_call = state["call"]
                    stream_events.append(
                        ToolExecutionCompleted(
                            tool_name=tool_call.name,
                            output=str(result.output),
                            is_error=bool(result.is_error),
                            tool_call_id=tool_call.id,
                            metadata=dict(result.metadata),
                        )
                    )

        for index in range(len(states)):
            state, result = finished[index]
            tool_call = state["call"]
            record_name = _canonical_tool_name(self.runtime, tool_call.name)
            self.runtime._record_tool(record_name, tool_call.arguments, result, tool_call_id=tool_call.id)
            self._record_tool_result(tool_call, result, is_mutating=state["is_mutating"])
            if self._tool_limits_exceeded():
                break
        return stream_events

    def _record_tool_result(self, tool_call, result, *, is_mutating: bool) -> None:
        self.query_stats["total_tool_calls"] += 1
        if result.is_error:
            self.query_stats["tool_failures"] += 1
            if is_mutating:
                self.query_stats["mutating_tool_failures"] += 1
        self.events.append(
            RuntimeEvent(
                kind="tool_result",
                payload={
                    "tool_name": tool_call.name,
                    "arguments": dict(tool_call.arguments),
                    "tool_call_id": tool_call.id,
                    "result": result.to_dict(),
                    "is_mutating": is_mutating,
                },
            )
        )

    def _tool_limits_exceeded(self) -> bool:
        if self.query_stats["total_tool_calls"] > self.query_settings.max_total_tool_calls:
            self.final_stop_reason = "max_total_tool_calls"
        elif self.query_stats["tool_failures"] > self.query_settings.max_tool_failures:
            self.final_stop_reason = "max_tool_failures"
        elif self.query_stats["mutating_tool_calls"] > self.runtime.settings.safety.max_mutating_tools_per_query:
            self.final_stop_reason = "max_mutating_tools_per_query"
        elif self.query_stats["mutating_tool_failures"] > self.runtime.settings.safety.max_mutating_tool_failures:
            self.final_stop_reason = "max_mutating_tool_failures"
        if self.final_stop_reason in {
            "max_total_tool_calls",
            "max_tool_failures",
            "max_mutating_tools_per_query",
            "max_mutating_tool_failures",
        }:
            self.events.append(RuntimeEvent(kind="query_stopped", payload={"reason": self.final_stop_reason}))
            return True
        return False

    def _should_stop_after_turn(self, turn) -> bool:
        if self.final_stop_reason in {
            "max_total_tool_calls",
            "max_tool_failures",
            "max_mutating_tools_per_query",
            "max_mutating_tool_failures",
        }:
            return True

        if turn.tool_calls:
            self.consecutive_tool_rounds += 1
            signature = _tool_signature(turn.tool_calls)
            self.tool_signature_counts[signature] = self.tool_signature_counts.get(signature, 0) + 1
            if self.tool_signature_counts[signature] > self.max_repeated_tool_call_signatures:
                self.events.append(
                    RuntimeEvent(
                        kind="query_stopped",
                        payload={"reason": "repeated_tool_signature", "signature": signature},
                    )
                )
                self.final_stop_reason = "repeated_tool_signature"
                return True
            if self.consecutive_tool_rounds > self.max_consecutive_tool_rounds:
                self.events.append(
                    RuntimeEvent(kind="query_stopped", payload={"reason": "max_consecutive_tool_rounds"})
                )
                self.final_stop_reason = "max_consecutive_tool_rounds"
                return True
        else:
            self.consecutive_tool_rounds = 0

        if self.empty_assistant_turns > self.max_empty_assistant_turns:
            self.events.append(RuntimeEvent(kind="query_stopped", payload={"reason": "max_empty_assistant_turns"}))
            self.final_stop_reason = "max_empty_assistant_turns"
            return True

        if self.repeated_assistant_turns > self.query_settings.max_repeated_assistant_turns:
            self.events.append(RuntimeEvent(kind="query_stopped", payload={"reason": "max_repeated_assistant_turns"}))
            self.final_stop_reason = "max_repeated_assistant_turns"
            return True

        if turn.stop or not turn.tool_calls:
            self.final_stop_reason = self.final_stop_reason or "end_turn"
            return True
        return False

    def _finish(self) -> QueryRunResult:
        self.runtime.current_provider_factory = None
        self.runtime.hook_executor.execute(
            "Stop",
            {"provider": self.provider.name, "message_count": len(self.runtime.messages)},
            cwd=self.runtime.workspace,
        )

        session_path = ""
        if self.runtime.settings.runtime.autosave_sessions:
            session_path = str(
                save_session_snapshot(
                    workspace=self.runtime.workspace,
                    model=self.runtime.settings.model,
                    system_prompt=self.system_prompt,
                    messages=self.runtime.messages[-self.runtime.settings.runtime.max_session_messages :],
                    usage={
                        "tool_calls": len(self.runtime.tool_history),
                        "provider": self.provider.name,
                        **self.usage_totals,
                    },
                    metadata={
                        "tool_history": [record.to_dict() for record in self.runtime.tool_history],
                        "active_command": self.runtime.active_command.to_dict() if self.runtime.active_command else None,
                        "active_command_arguments": self.runtime.active_command_arguments,
                        "query_stats": self.query_stats,
                        "stop_reason": self.final_stop_reason,
                        "turn_count": self.turn_count,
                        "events": [event.to_dict() for event in self.events] if self.runtime.settings.runtime.save_turn_events else [],
                    },
                )
            )

        result = QueryRunResult(
            events=[event.to_dict() for event in self.events],
            messages=list(self.runtime.messages),
            session_path=session_path,
            provider_name=self.provider.name,
            usage=dict(self.usage_totals),
            query_stats=dict(self.query_stats),
            stop_reason=self.final_stop_reason,
            turn_count=self.turn_count,
        )
        self.runtime.last_query_result = result
        return result


def _tool_signature(tool_calls) -> str:
    payload = [{"name": call.name, "arguments": call.arguments} for call in tool_calls]
    return json.dumps(payload, sort_keys=True, ensure_ascii=True)


def _chunk_text(text: str, *, chunk_size: int) -> list[str]:
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def _clone_provider(provider: BaseProvider) -> BaseProvider:
    try:
        return provider.clone()
    except Exception:
        return provider


def _messages_for_provider(
    messages: list[dict[str, Any]],
    *,
    max_messages: int,
    max_chars: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    selected_units = _message_units(messages)
    selected = _flatten_units(selected_units)
    if len(selected) <= max_messages and _messages_char_count(selected) <= max_chars:
        return _provider_safe_messages(selected)

    preserve_recent = max(2, min(4, max_messages // 4 if max_messages > 0 else 2))
    compacted_units, compact_payload = _compact_message_units_for_context(
        selected_units,
        preserve_recent=preserve_recent,
    )
    selected_units = compacted_units
    selected = _flatten_units(selected_units)
    if len(selected) <= max_messages and _messages_char_count(selected) <= max_chars:
        return _provider_safe_messages(selected, compact_payload)

    truncation_payload: dict[str, Any] | None = compact_payload
    if len(selected) > max_messages:
        before = len(selected)
        selected_units = _take_recent_units_by_message_budget(selected_units, max_messages=max_messages)
        selected = _flatten_units(selected_units)
        truncation_payload = {
            "reason": "max_context_messages",
            "removed_messages": before - len(selected),
            "kept_messages": len(selected),
            "after_compaction": compact_payload is not None,
        }

    total_chars = _messages_char_count(selected)
    if total_chars > max_chars:
        before = len(selected)
        selected_units = _take_recent_units_by_char_budget(selected_units, max_chars=max_chars)
        selected = _flatten_units(selected_units)
        truncation_payload = {
            "reason": "max_context_chars",
            "removed_messages": before - len(selected),
            "kept_messages": len(selected),
            "kept_chars": _messages_char_count(selected),
            "after_compaction": compact_payload is not None,
        }
    return _provider_safe_messages(selected, truncation_payload)


def _compact_message_units_for_context(
    units: list[list[dict[str, Any]]],
    *,
    preserve_recent: int,
) -> tuple[list[list[dict[str, Any]]], dict[str, Any] | None]:
    if len(units) <= preserve_recent:
        return [list(unit) for unit in units], None

    older_units = units[:-preserve_recent]
    newer_units = units[-preserve_recent:]
    older = _flatten_units(older_units)
    summary = _summarize_messages(older)
    if not summary:
        return [list(unit) for unit in newer_units], None

    summary_unit = [ChatMessage(
        role="assistant",
        text=f"[conversation summary]\n{summary}",
        metadata={"kind": "conversation_summary"},
    ).to_dict()]
    payload = {
        "reason": "conversation_compacted",
        "removed_messages": len(older),
        "kept_messages": len(_flatten_units(newer_units)) + 1,
        "summary_chars": len(summary),
    }
    return [summary_unit, *[list(unit) for unit in newer_units]], payload


def _summarize_messages(messages: Iterable[dict[str, Any]], *, max_lines: int = 16) -> str:
    lines: list[str] = []
    for message in messages:
        role = str(message.get("role", "unknown"))
        text = str(message.get("text", "")).strip()
        if not text and role == "tool":
            tool_name = message.get("tool_name") or "tool"
            text = f"{tool_name}: {str(message.get('text', '')).strip()}"
        if not text:
            continue
        lines.append(f"{role}: {text[:240]}")
        if len(lines) >= max_lines:
            break
    return "\n".join(lines)


def _messages_char_count(messages: list[dict[str, Any]]) -> int:
    return sum(len(str(message.get("text", ""))) for message in messages)


def _message_units(messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
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


def _flatten_units(units: Iterable[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for unit in units:
        flattened.extend(unit)
    return flattened


def _take_recent_units_by_message_budget(
    units: list[list[dict[str, Any]]],
    *,
    max_messages: int,
) -> list[list[dict[str, Any]]]:
    kept: list[list[dict[str, Any]]] = []
    running_messages = 0
    for unit in reversed(units):
        unit_count = len(unit)
        if kept and running_messages + unit_count > max_messages:
            break
        if not kept and unit_count > max_messages:
            kept.append([_summary_message_for_unit(unit, kind="message_budget_summary")])
            break
        kept.append(unit)
        running_messages += unit_count
    kept.reverse()
    return kept or [[_summary_message_for_unit(_flatten_units(units[-1:]), kind="message_budget_summary")]]


def _take_recent_units_by_char_budget(
    units: list[list[dict[str, Any]]],
    *,
    max_chars: int,
) -> list[list[dict[str, Any]]]:
    kept: list[list[dict[str, Any]]] = []
    running_chars = 0
    for unit in reversed(units):
        unit_chars = _messages_char_count(unit)
        if kept and running_chars + unit_chars > max_chars:
            break
        if not kept and unit_chars > max_chars:
            kept.append([_summary_message_for_unit(unit, kind="char_budget_summary")])
            break
        kept.append(unit)
        running_chars += unit_chars
    kept.reverse()
    return kept or [[_summary_message_for_unit(_flatten_units(units[-1:]), kind="char_budget_summary")]]


def _summary_message_for_unit(unit: Iterable[dict[str, Any]], *, kind: str) -> dict[str, Any]:
    summary = _summarize_messages(list(unit), max_lines=8) or "Recent tool-heavy context was compacted to fit the provider window."
    return ChatMessage(
        role="assistant",
        text=f"[conversation summary]\n{summary}",
        metadata={"kind": kind},
    ).to_dict()


def _provider_safe_messages(
    messages: list[dict[str, Any]],
    payload: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    sanitized: list[dict[str, Any]] = []
    dropped_orphans: list[dict[str, Any]] = []
    active_tool_call_ids: set[str] = set()

    for message in messages:
        role = str(message.get("role", ""))
        if role == "assistant":
            sanitized.append(message)
            active_tool_call_ids = {
                str(call.get("id", ""))
                for call in list(message.get("tool_calls", []) or [])
                if str(call.get("id", ""))
            }
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
    return sanitized, (event_payload or None)


def _build_synthesis_instruction(
    *,
    prompt: str,
    messages: list[dict[str, Any]],
    tool_history,
    reason: str,
) -> str:
    recent_user = ""
    for message in reversed(messages):
        if message.get("role") == "user":
            recent_user = str(message.get("text", "")).strip()
            if recent_user:
                break
    recent_tools = [record.tool_name for record in tool_history[-6:]]
    recent_tool_text = ", ".join(recent_tools) if recent_tools else "(none)"
    rationale = {
        "max_empty_assistant_turns": "Recent tool rounds produced too little assistant narration and the loop must converge now.",
        "max_consecutive_tool_rounds": "The query loop has already spent many consecutive turns on tool use.",
        "last_turn_force_summary": "This is the last turn budget, so the answer must converge now.",
    }.get(reason, "The query loop needs to converge now.")
    return (
        "[query loop guard]\n"
        f"{rationale}\n"
        "Do not call any more tools in this turn.\n"
        "Synthesize a final answer from the evidence already gathered.\n"
        "Prefer concrete file paths, architecture explanation, and the best next step.\n"
        "Prefer plain ASCII headings, bullets, and code fences over decorative Unicode trees or box art.\n"
        "If evidence is still incomplete, say exactly what is missing instead of continuing to explore.\n"
        f"Original request: {prompt.strip()}\n"
        f"Latest user wording: {recent_user or prompt.strip()}\n"
        f"Recent tools: {recent_tool_text}"
    )


def _canonical_tool_name(runtime: HarnessRuntime, name: str) -> str:
    tool = runtime.tool_registry.get(name)
    if tool is None:
        return name
    return tool.name


def _is_mutating_tool(runtime: HarnessRuntime, name: str, arguments: dict[str, Any]) -> bool:
    tool = runtime.tool_registry.get(name)
    if tool is None:
        return True
    return not tool.is_read_only(arguments)


def _is_parallel_safe_tool(runtime: HarnessRuntime, name: str) -> bool:
    tool = runtime.tool_registry.get(name)
    if tool is None:
        return False
    return bool(getattr(tool, "parallel_safe", True))
