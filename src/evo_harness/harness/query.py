from __future__ import annotations

import json
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from evo_harness.harness.context_window import ContextWindowPolicy, message_window_text, prepare_messages_for_provider
from evo_harness.harness.messages import ChatMessage
from evo_harness.harness.provider import BaseProvider
from evo_harness.harness.runtime import HarnessRuntime, RuntimeEvent
from evo_harness.harness.session import save_session_snapshot
from evo_harness.harness.stream_events import (
    AssistantTextDelta,
    AssistantTurnComplete,
    ToolExecutionCompleted,
    ToolExecutionProgress,
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
    attachments: list[dict[str, Any]] | None = None,
    provider: BaseProvider,
    command_name: str | None = None,
    command_arguments: str = "",
    max_turns: int = 8,
) -> QueryRunResult:
    runner = _QueryRunner(
        runtime,
        prompt=prompt,
        attachments=attachments,
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
    attachments: list[dict[str, Any]] | None = None,
    provider: BaseProvider,
    command_name: str | None = None,
    command_arguments: str = "",
    max_turns: int = 8,
):
    runner = _QueryRunner(
        runtime,
        prompt=prompt,
        attachments=attachments,
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
        attachments: list[dict[str, Any]] | None,
        provider: BaseProvider,
        command_name: str | None,
        command_arguments: str,
        max_turns: int,
    ) -> None:
        self.runtime = runtime
        self.prompt = prompt
        self.attachments = [dict(item) for item in list(attachments or [])]
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
                for event in self._execute_tool_calls_stream(turn.tool_calls):
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
        user_message = ChatMessage(role="user", text=self.prompt, attachments=self.attachments)
        self.runtime.messages.append(user_message.to_dict())
        self.events.append(
            RuntimeEvent(
                kind="user_message",
                payload={"text": self.prompt, "attachments": [dict(item) for item in self.attachments]},
            )
        )
        self._started = True

    def _next_turn(self, turn_index: int):
        self.turn_count += 1
        provider_messages, window_event = _messages_for_provider(
            self.runtime.messages,
            max_messages=self.query_settings.max_context_messages,
            max_chars=self.query_settings.max_context_chars,
            preserve_recent_messages=self.query_settings.context_compaction_preserve_recent_messages,
            summary_max_lines=self.query_settings.context_summary_max_lines,
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

    def _execute_tool_calls_stream(self, tool_calls):
        if not tool_calls:
            return

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
            for event in self._execute_tool_calls_parallel(states, emit_stream=True):
                yield event
            return

        for state in states:
            tool_call = state["call"]
            yield ToolExecutionStarted(
                tool_name=tool_call.name,
                tool_input=dict(tool_call.arguments),
                tool_call_id=tool_call.id,
            )
            progress_queue: queue.Queue[dict[str, Any]] = queue.Queue()

            def _progress_callback(payload: dict[str, Any]) -> None:
                progress_queue.put(dict(payload))

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    self.runtime.execute_tool,
                    tool_call.name,
                    tool_call.arguments,
                    tool_call_id=tool_call.id,
                    progress_callback=_progress_callback,
                )
                while True:
                    try:
                        progress = progress_queue.get(timeout=0.1)
                        text = str(progress.get("text", "") or "").strip()
                        if text:
                            yield ToolExecutionProgress(
                                tool_name=tool_call.name,
                                output=text,
                                stream=str(progress.get("stream", "stdout") or "stdout"),
                                tool_call_id=tool_call.id,
                            )
                    except queue.Empty:
                        if future.done():
                            break
                while not progress_queue.empty():
                    progress = progress_queue.get_nowait()
                    text = str(progress.get("text", "") or "").strip()
                    if text:
                        yield ToolExecutionProgress(
                            tool_name=tool_call.name,
                            output=text,
                            stream=str(progress.get("stream", "stdout") or "stdout"),
                            tool_call_id=tool_call.id,
                        )
                result = future.result()

            self._record_tool_result(tool_call, result, is_mutating=state["is_mutating"])
            yield ToolExecutionCompleted(
                tool_name=tool_call.name,
                output=str(result.output),
                is_error=bool(result.is_error),
                tool_call_id=tool_call.id,
                metadata=dict(result.metadata),
            )
            if self._tool_limits_exceeded():
                break

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
                # Keep the full registry visible inside read-only parallel tool executions.
                # Introspection tools such as workspace_status and list_registry need the real
                # workspace surface, not a single-tool sandbox created only for dispatch.
                subruntime = self.runtime.create_subruntime()
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
                        "provider_config": {
                            "model": self.runtime.settings.model,
                            "provider": self.runtime.settings.provider.provider,
                            "profile": self.runtime.settings.provider.profile,
                            "api_format": self.runtime.settings.provider.api_format,
                            "api_key_env": self.runtime.settings.provider.api_key_env,
                            "base_url": self.runtime.settings.provider.base_url,
                            "auth_scheme": self.runtime.settings.provider.auth_scheme,
                            "headers": dict(self.runtime.settings.provider.headers),
                        },
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
        if self.runtime.settings.runtime.auto_self_evolution:
            try:
                from evo_harness.autonomous_evolution import (
                    run_autonomous_self_evolution,
                    write_autonomous_failure_record,
                )

                run_autonomous_self_evolution(
                    self.runtime.workspace,
                    settings=self.runtime.settings,
                    provider=_clone_provider(self.provider),
                    session_id="latest",
                    mode=self.runtime.settings.runtime.auto_self_evolution_mode,
                )
            except Exception as exc:
                try:
                    write_autonomous_failure_record(
                        self.runtime.workspace,
                        session_id="latest",
                        error=str(exc),
                    )
                except Exception:
                    pass
                self.events.append(
                    RuntimeEvent(
                        kind="autonomous_evolution_failed",
                        payload={"error": str(exc)},
                    )
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
    preserve_recent_messages: int = 4,
    summary_max_lines: int = 16,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    return prepare_messages_for_provider(
        messages,
        policy=ContextWindowPolicy(
            max_messages=max_messages,
            max_chars=max_chars,
            preserve_recent_messages=preserve_recent_messages,
            summary_max_lines=summary_max_lines,
        ),
    )


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
            recent_user = message_window_text(message).strip()
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
