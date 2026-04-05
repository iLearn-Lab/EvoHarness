from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from evo_harness.harness.frontmatter import parse_frontmatter, split_list_like
from evo_harness.harness.plugins import load_workspace_plugins
from evo_harness.harness.settings import HarnessSettings, load_settings


@dataclass(slots=True)
class CommandDefinition:
    name: str
    description: str
    content: str
    path: str
    source: str
    argument_hint: str = ""
    allowed_tools: list[str] | None = None
    model: str | None = None
    max_turns: int | None = None
    tags: list[str] = field(default_factory=list)
    requires_plugins: list[str] = field(default_factory=list)

    def render(self, arguments: str = "") -> str:
        return self.content.replace("$ARGUMENTS", arguments.strip())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_workspace_commands(workspace: str | Path, settings: HarnessSettings | None = None) -> list[CommandDefinition]:
    root = Path(workspace).resolve()
    settings = settings or load_settings(workspace=root)
    commands: list[CommandDefinition] = []
    patterns = [
        (".claude/commands/*.md", "claude"),
        (".openharness/commands/*.md", "openharness"),
        ("commands/*.md", "workspace"),
    ]
    for pattern, source in patterns:
        for path in sorted(root.glob(pattern)):
            commands.append(_command_from_path(path, source))
    for plugin in load_workspace_plugins(root, settings=settings):
        plugin_root = Path(plugin.path)
        commands_dir = plugin_root / plugin.manifest.commands_dir
        if not commands_dir.exists():
            continue
        for path in sorted(commands_dir.glob("*.md")):
            commands.append(_command_from_path(path, f"plugin:{plugin.manifest.name}"))
    return commands


def find_command(workspace: str | Path, name: str) -> CommandDefinition | None:
    for command in load_workspace_commands(workspace):
        if command.name == name:
            return command
    return None


def _command_from_path(path: Path, source: str) -> CommandDefinition:
    content = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(content)
    name = str(frontmatter.get("name", path.stem))
    max_turns = frontmatter.get("max-turns")
    return CommandDefinition(
        name=name,
        description=str(frontmatter.get("description", f"Command: {name}")),
        argument_hint=str(frontmatter.get("argument-hint", "")),
        allowed_tools=split_list_like(frontmatter.get("allowed-tools")),
        model=frontmatter.get("model"),
        max_turns=int(max_turns) if isinstance(max_turns, (int, float)) else None,
        tags=split_list_like(frontmatter.get("tags")) or [],
        requires_plugins=split_list_like(frontmatter.get("requires-plugins")) or [],
        content=body,
        path=str(path),
        source=source,
    )
