from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from evo_harness.harness.plugins import load_workspace_plugins
from evo_harness.harness.settings import HarnessSettings, load_settings


@dataclass(slots=True)
class SkillDefinition:
    name: str
    description: str
    content: str
    path: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def load_workspace_skills(workspace: str | Path, settings: HarnessSettings | None = None) -> list[SkillDefinition]:
    root = Path(workspace).resolve()
    settings = settings or load_settings(workspace=root)
    skills: list[SkillDefinition] = []
    patterns = [
        (".openharness/skills/*.md", "openharness"),
        (".claude/skills/*.md", "claude"),
        ("skills/*.md", "workspace"),
    ]
    for pattern, source in patterns:
        for path in sorted(root.glob(pattern)):
            skills.append(_skill_from_path(path, source))
    for plugin in load_workspace_plugins(root, settings=settings):
        plugin_root = Path(plugin.path)
        skills_dir = plugin_root / plugin.manifest.skills_dir
        if not skills_dir.exists():
            continue
        for path in sorted(skills_dir.glob("*.md")):
            skills.append(_skill_from_path(path, f"plugin:{plugin.manifest.name}"))
    return skills


def _parse_skill_markdown(default_name: str, content: str) -> tuple[str, str]:
    name = default_name
    description = ""
    lines = content.splitlines()

    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                for frontmatter_line in lines[1:i]:
                    stripped = frontmatter_line.strip()
                    if stripped.startswith("name:"):
                        value = stripped[5:].strip().strip("'\"")
                        if value:
                            name = value
                    if stripped.startswith("description:"):
                        value = stripped[12:].strip().strip("'\"")
                        if value:
                            description = value
                break

    if not description:
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("# ") and name == default_name:
                name = stripped[2:].strip() or default_name
                continue
            if stripped and not stripped.startswith("#") and not stripped.startswith("---"):
                description = stripped[:200]
                break

    if not description:
        description = f"Skill: {name}"
    return name, description


def _skill_from_path(path: Path, source: str) -> SkillDefinition:
    content = path.read_text(encoding="utf-8")
    name, description = _parse_skill_markdown(path.stem, content)
    return SkillDefinition(
        name=name,
        description=description,
        content=content,
        path=str(path),
        source=source,
    )
