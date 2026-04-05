from __future__ import annotations

from pathlib import Path
from re import findall
from re import sub

from evo_harness.harness.content_windows import context_safe_output


def load_memory_prompt(workspace: str | Path, *, max_chars: int = 8000) -> str | None:
    index_path = get_memory_index_path(workspace)
    if not index_path.exists():
        return None
    content = index_path.read_text(encoding="utf-8", errors="replace").strip()
    if not content:
        return None
    if len(content) > max_chars:
        content, _metadata = context_safe_output(content, limit=max_chars)
    return "\n".join(["# Persistent Memory", "```md", content, "```"])


def find_relevant_memory_entries(
    query: str,
    workspace: str | Path,
    *,
    max_results: int = 4,
) -> list[Path]:
    tokens = {token for token in findall(r"[A-Za-z0-9_]+", query.lower()) if len(token) >= 3}
    if not tokens:
        return []

    scored: list[tuple[int, float, Path]] = []
    for path in list_memory_entries(workspace):
        content = path.read_text(encoding="utf-8", errors="replace")
        haystack = f"{path.stem} {content[:2000]}".lower()
        score = sum(1 for token in tokens if token in haystack)
        if score:
            scored.append((score, path.stat().st_mtime, path))

    scored.sort(key=lambda item: (-item[0], -item[1]))
    return [path for _score, _mtime, path in scored[:max_results]]


def render_memory_entry(path: str | Path, *, max_chars: int = 8000) -> str:
    content = Path(path).read_text(encoding="utf-8", errors="replace").strip()
    if len(content) > max_chars:
        content, _metadata = context_safe_output(content, limit=max_chars)
    return content


def get_memory_index_path(workspace: str | Path) -> Path:
    root = Path(workspace).resolve()
    return root / "MEMORY.md"


def get_memory_dir(workspace: str | Path) -> Path:
    root = Path(workspace).resolve()
    path = root / ".evo-harness" / "memory"
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_memory_entries(workspace: str | Path) -> list[Path]:
    return sorted(get_memory_dir(workspace).glob("*.md"))


def add_memory_entry(workspace: str | Path, title: str, content: str) -> Path:
    memory_dir = get_memory_dir(workspace)
    slug = sub(r"[^a-zA-Z0-9]+", "_", title.strip().lower()).strip("_") or "memory"
    path = memory_dir / f"{slug}.md"
    path.write_text(content.strip() + "\n", encoding="utf-8")

    index_path = get_memory_index_path(workspace)
    if not index_path.exists():
        index_path.write_text("# Memory\n", encoding="utf-8")
    existing = index_path.read_text(encoding="utf-8")
    relative = path.relative_to(Path(workspace).resolve())
    if str(relative) not in existing:
        updated = existing.rstrip() + f"\n- [{title}]({relative.as_posix()})\n"
        index_path.write_text(updated, encoding="utf-8")
    return path


def remove_memory_entry(workspace: str | Path, name: str) -> bool:
    matches = [
        path
        for path in get_memory_dir(workspace).glob("*.md")
        if path.stem == name or path.name == name
    ]
    if not matches:
        return False
    target = matches[0]
    target.unlink(missing_ok=True)

    index_path = get_memory_index_path(workspace)
    if index_path.exists():
        lines = [
            line
            for line in index_path.read_text(encoding="utf-8").splitlines()
            if target.name not in line
        ]
        index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return True
