from __future__ import annotations

from pathlib import Path
from re import findall
from re import sub
import json

from evo_harness.harness.content_windows import context_safe_output
from evo_harness.harness.messages import ChatMessage


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
    tokens = _memory_query_tokens(query)
    if not tokens:
        return []

    scored: list[tuple[int, float, Path]] = []
    for path in list_memory_entries(workspace):
        content = path.read_text(encoding="utf-8", errors="replace")
        haystack = f"{path.stem} {content[:2000]}".lower()
        overlap = [token for token in tokens if token in haystack]
        score = sum(3 if token in path.stem.lower() else 1 for token in overlap)
        if score >= 3 or len(overlap) >= 2:
            scored.append((score, path.stat().st_mtime, path))

    scored.sort(key=lambda item: (-item[0], -item[1]))
    return [path for _score, _mtime, path in scored[:max_results]]


def _memory_query_tokens(query: str) -> set[str]:
    lowered = str(query or "").lower()
    ascii_tokens = {token for token in findall(r"[A-Za-z0-9_]+", lowered) if len(token) >= 3}
    cjk_tokens = {token for token in findall(r"[\u4e00-\u9fff]{2,}", lowered) if len(token) >= 2}
    return ascii_tokens | cjk_tokens


def select_relevant_memory_entries(
    query: str,
    workspace: str | Path,
    *,
    settings=None,
    provider=None,
    prefilter_limit: int = 4,
    max_results: int = 2,
) -> list[Path]:
    candidates = find_relevant_memory_entries(query, workspace, max_results=prefilter_limit)
    if len(candidates) <= 1:
        return candidates[:max_results]
    judged = _judge_memory_candidates(query, candidates, settings=settings, provider=provider, max_results=max_results)
    if judged:
        return judged[:max_results]
    return candidates[:max_results]


def _judge_memory_candidates(
    query: str,
    candidates: list[Path],
    *,
    settings=None,
    provider=None,
    max_results: int,
) -> list[Path]:
    if not candidates:
        return []
    try:
        active_provider = provider
        if active_provider is None:
            if settings is None:
                return []
            from evo_harness.harness.provider import build_live_provider

            active_provider = build_live_provider(settings=settings)
        prompt_lines = [
            "Choose the memory files that are genuinely relevant to the current task.",
            "Only select memories that would materially help solve the user's current request.",
            "Return JSON only in the form {\"selected\": [\"file1.md\", \"file2.md\"]}.",
            f"Current task: {query[:500]}",
            "",
            "Candidate memories:",
        ]
        for path in candidates:
            preview = path.read_text(encoding="utf-8", errors="replace").strip().replace("\n", " ")[:400]
            prompt_lines.append(f"- {path.name}: {preview}")
        turn = active_provider.next_turn(
            system_prompt="You are a memory relevance judge. Be strict and prefer selecting fewer memories.",
            messages=[ChatMessage(role="user", text="\n".join(prompt_lines))],
            tool_schema=[],
        )
        selected_names = _parse_selected_memory_names(str(turn.assistant_text or "").strip())
        if not selected_names:
            return []
        by_name = {path.name: path for path in candidates}
        return [by_name[name] for name in selected_names if name in by_name][:max_results]
    except Exception:
        return []


def _parse_selected_memory_names(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    candidates = [stripped]
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first != -1 and last != -1 and first < last:
        candidates.append(stripped[first : last + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        selected = payload.get("selected", [])
        if isinstance(selected, list):
            return [str(item).strip() for item in selected if str(item).strip()]
    return []


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
