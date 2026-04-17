from __future__ import annotations

from pathlib import Path

from evo_harness.models import WorkspaceSnapshot


def discover_workspace(root: str | Path) -> WorkspaceSnapshot:
    """Discover Claude-Code-like and OpenHarness-like workspace conventions."""

    resolved = Path(root).resolve()
    claude_files: list[str] = []
    memory_files: list[str] = []
    skill_files: list[str] = []
    command_files: list[str] = []
    agent_files: list[str] = []
    hook_files: list[str] = []

    for directory in [resolved, *resolved.parents]:
        for candidate in (
            directory / "CLAUDE.md",
            directory / "CLAUDE.local.md",
            directory / ".claude" / "CLAUDE.md",
            directory / ".openharness" / "CLAUDE.md",
        ):
            if candidate.exists():
                claude_files.append(str(candidate))
        if directory.parent == directory:
            break

    for candidate in (
        resolved / "MEMORY.md",
        resolved / ".openharness" / "MEMORY.md",
        resolved / ".claude" / "MEMORY.md",
    ):
        if candidate.exists():
            memory_files.append(str(candidate))

    for pattern in (
        ".openharness/skills/*.md",
        ".claude/skills/*.md",
        "skills/*.md",
        "plugins/*/skills/*.md",
    ):
        for path in sorted(resolved.glob(pattern)):
            skill_files.append(str(path))

    for pattern in (
        ".claude/commands/*.md",
        ".openharness/commands/*.md",
        "commands/*.md",
        "plugins/*/commands/*.md",
    ):
        for path in sorted(resolved.glob(pattern)):
            command_files.append(str(path))

    for pattern in (
        ".claude/agents/*.md",
        ".openharness/agents/*.md",
        "agents/*.md",
        "plugins/*/agents/*.md",
    ):
        for path in sorted(resolved.glob(pattern)):
            agent_files.append(str(path))

    for pattern in (
        ".openharness/hooks/*.json",
        ".claude/hooks/*.json",
        "hooks/*.json",
        "plugins/*/hooks/*.json",
    ):
        for path in sorted(resolved.glob(pattern)):
            hook_files.append(str(path))

    return WorkspaceSnapshot(
        root=str(resolved),
        claude_files=sorted(set(claude_files)),
        memory_files=sorted(set(memory_files)),
        skill_files=sorted(set(skill_files)),
        command_files=sorted(set(command_files)),
        agent_files=sorted(set(agent_files)),
        hook_files=sorted(set(hook_files)),
    )
