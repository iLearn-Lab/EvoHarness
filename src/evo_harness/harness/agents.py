from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from evo_harness.harness.frontmatter import parse_frontmatter, split_list_like
from evo_harness.harness.plugins import load_workspace_plugins
from evo_harness.harness.settings import HarnessSettings, load_settings


@dataclass(slots=True)
class AgentDefinition:
    name: str
    description: str
    content: str
    path: str
    source: str
    tools: list[str] | None = None
    model: str | None = None
    max_turns: int | None = None
    share_history: bool | None = None
    include_parent_summary: bool | None = None
    parallel_safe: bool = False
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_workspace_agents(workspace: str | Path, settings: HarnessSettings | None = None) -> list[AgentDefinition]:
    root = Path(workspace).resolve()
    settings = settings or load_settings(workspace=root)
    agents: list[AgentDefinition] = []
    patterns = [
        (".claude/agents/*.md", "claude"),
        (".openharness/agents/*.md", "openharness"),
        ("agents/*.md", "workspace"),
    ]
    for pattern, source in patterns:
        for path in sorted(root.glob(pattern)):
            agents.append(_agent_from_path(path, source))
    for plugin in load_workspace_plugins(root, settings=settings):
        plugin_root = Path(plugin.path)
        agents_dir = plugin_root / plugin.manifest.agents_dir
        if not agents_dir.exists():
            continue
        for path in sorted(agents_dir.glob("*.md")):
            agents.append(_agent_from_path(path, f"plugin:{plugin.manifest.name}"))
    return agents


def find_agent(workspace: str | Path, name: str) -> AgentDefinition | None:
    for agent in load_workspace_agents(workspace):
        if agent.name == name:
            return agent
    return None


def _agent_from_path(path: Path, source: str) -> AgentDefinition:
    content = path.read_text(encoding="utf-8")
    frontmatter, body = parse_frontmatter(content)
    max_turns = frontmatter.get("max-turns")
    share_history = frontmatter.get("share-history")
    include_parent_summary = frontmatter.get("include-parent-summary")
    return AgentDefinition(
        name=str(frontmatter.get("name", path.stem)),
        description=str(frontmatter.get("description", f"Agent: {path.stem}")),
        content=body,
        path=str(path),
        source=source,
        tools=split_list_like(frontmatter.get("tools")),
        model=frontmatter.get("model"),
        max_turns=int(max_turns) if isinstance(max_turns, (int, float)) else None,
        share_history=bool(share_history) if isinstance(share_history, bool) else None,
        include_parent_summary=(
            bool(include_parent_summary) if isinstance(include_parent_summary, bool) else None
        ),
        parallel_safe=bool(frontmatter.get("parallel-safe", False)),
        tags=split_list_like(frontmatter.get("tags")) or [],
    )
