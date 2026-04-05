from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class ChatMessage:
    role: str
    text: str = ""
    tool_name: str | None = None
    is_error: bool = False
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ProviderTurn:
    assistant_text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "assistant_text": self.assistant_text,
            "tool_calls": [call.to_dict() for call in self.tool_calls],
            "stop": self.stop,
            "metadata": self.metadata,
        }
