from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from evo_harness.harness.provider import BaseProvider
from evo_harness.harness.query import QueryRunResult, run_query, run_query_stream
from evo_harness.harness.runtime import HarnessRuntime
from evo_harness.harness.session import load_session_snapshot


@dataclass
class ConversationEngine:
    runtime: HarnessRuntime

    def clear(self) -> None:
        self.runtime.reset()

    def load_session(self, session_id: str = "latest") -> bool:
        snapshot = load_session_snapshot(self.runtime.workspace, session_id=session_id)
        if snapshot is None:
            return False
        self.runtime.reset()
        self.runtime.messages.extend(list(snapshot.get("messages", [])))
        metadata = dict(snapshot.get("metadata", {}))
        active_command = dict(metadata.get("active_command") or {})
        if active_command.get("name"):
            try:
                self.runtime.set_active_command(
                    str(active_command["name"]),
                    str(metadata.get("active_command_arguments", "")),
                )
            except KeyError:
                pass
        return True

    def submit(
        self,
        *,
        prompt: str,
        provider: BaseProvider,
        command_name: str | None = None,
        command_arguments: str = "",
        max_turns: int | None = None,
    ) -> QueryRunResult:
        return run_query(
            self.runtime,
            prompt=prompt,
            provider=provider,
            command_name=command_name,
            command_arguments=command_arguments,
            max_turns=max_turns or self.runtime.settings.query.max_turns,
        )

    def submit_stream(
        self,
        *,
        prompt: str,
        provider: BaseProvider,
        command_name: str | None = None,
        command_arguments: str = "",
        max_turns: int | None = None,
    ):
        return run_query_stream(
            self.runtime,
            prompt=prompt,
            provider=provider,
            command_name=command_name,
            command_arguments=command_arguments,
            max_turns=max_turns or self.runtime.settings.query.max_turns,
        )
