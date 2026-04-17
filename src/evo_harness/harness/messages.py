from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ChatMessage:
    role: str
    text: str = ""
    tool_name: str | None = None
    is_error: bool = False
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)
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


def render_attachment_summary(
    attachments: list[dict[str, Any]],
    *,
    include_path: bool = False,
    max_items: int = 4,
) -> str:
    lines: list[str] = []
    for index, attachment in enumerate(attachments[:max_items], start=1):
        kind = str(attachment.get("kind", "attachment") or "attachment").strip().lower()
        label = "Image" if kind == "image" else kind.capitalize()
        file_name = str(
            attachment.get("file_name")
            or Path(str(attachment.get("path", "") or "")).name
            or f"{kind or 'attachment'}-{index}"
        ).strip()
        parts = [f"[{label} #{index}] {file_name}"]
        width = attachment.get("width")
        height = attachment.get("height")
        if width and height:
            parts.append(f"{width}x{height}")
        byte_count = int(attachment.get("byte_count", 0) or 0)
        if byte_count > 0:
            parts.append(f"{byte_count} bytes")
        source = str(attachment.get("source", "") or "").strip()
        if source:
            parts.append(f"source={source}")
        if include_path:
            path = str(attachment.get("path", "") or "").strip()
            if path:
                parts.append(f"path={path}")
        lines.append(" ".join(parts[:1]) + (f" ({', '.join(parts[1:])})" if len(parts) > 1 else ""))
    extra = len(attachments) - len(lines)
    if extra > 0:
        lines.append(f"... and {extra} more attachment(s)")
    return "\n".join(lines)


def render_message_text(
    message: dict[str, Any],
    *,
    include_attachment_paths: bool = False,
) -> str:
    text = str(message.get("text", "")).strip()
    attachments = list(message.get("attachments", []) or [])
    if not attachments:
        return text
    attachment_text = render_attachment_summary(
        attachments,
        include_path=include_attachment_paths,
    )
    if not text:
        return attachment_text
    return f"{text}\n{attachment_text}"
