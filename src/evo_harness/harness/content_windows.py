from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import ceil
import re
from typing import Any


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "const",
    "def",
    "do",
    "else",
    "export",
    "false",
    "for",
    "from",
    "function",
    "if",
    "import",
    "in",
    "is",
    "it",
    "let",
    "none",
    "not",
    "null",
    "of",
    "or",
    "return",
    "self",
    "str",
    "the",
    "this",
    "to",
    "true",
    "type",
    "var",
    "void",
    "with",
}

_HIGHLIGHT_PATTERNS = [
    re.compile(r"^\s*#{1,6}\s+\S"),
    re.compile(r"^\s*(class|def|async def)\s+\w+"),
    re.compile(r"^\s*(export\s+)?(async\s+)?function\s+\w+"),
    re.compile(r"^\s*(export\s+)?(const|let|var)\s+\w+\s*="),
    re.compile(r"^\s*(interface|type|enum)\s+\w+"),
    re.compile(r"\b(TODO|FIXME|NOTE|WARNING)\b", re.IGNORECASE),
]


@dataclass(slots=True)
class MatchHit:
    source: str
    text: str
    line_number: int | None = None


def summarize_text_block(
    text: str,
    *,
    max_highlights: int = 4,
    max_keywords: int = 6,
) -> dict[str, Any]:
    lines = text.splitlines()
    highlights = _highlight_lines(lines, max_items=max_highlights)
    keywords = _top_keywords(text, max_items=max_keywords)
    return {
        "line_count": len(lines) if lines else (1 if text else 0),
        "char_count": len(text),
        "highlights": highlights,
        "keywords": keywords,
    }


def format_segmented_file_view(
    *,
    path: str,
    text: str,
    start_line: int | None = None,
    end_line: int | None = None,
    segment: int | None = None,
    segment_lines: int = 120,
) -> tuple[str, dict[str, Any]]:
    lines = text.splitlines()
    total_lines = len(lines) if lines else 1
    segment_lines = max(20, min(int(segment_lines or 120), 400))
    explicit_range = start_line is not None or end_line is not None
    explicit_segment = segment is not None
    large_file = total_lines > segment_lines or len(text) > 12000

    if not explicit_range and not explicit_segment and not large_file:
        return text, {"path": path, "line_count": total_lines, "char_count": len(text)}

    if explicit_segment:
        segment_index = max(1, int(segment or 1))
        selected_start = ((segment_index - 1) * segment_lines) + 1
        selected_end = min(total_lines, segment_index * segment_lines)
    elif not explicit_range and large_file:
        segment_index = 1
        selected_start = 1
        selected_end = min(total_lines, segment_lines)
    else:
        selected_start = max(1, int(start_line or 1))
        selected_end = min(total_lines, int(end_line or total_lines))
        segment_index = max(1, ceil(selected_start / segment_lines))

    if selected_start > total_lines:
        selected_start = total_lines
    if selected_end < selected_start:
        selected_end = selected_start

    segment_count = max(1, ceil(total_lines / segment_lines))
    selected_lines = lines[selected_start - 1 : selected_end] if lines else [text]
    numbered = _numbered_lines(selected_lines, start_line=selected_start)
    summary = summarize_text_block(text)

    lines_out = [
        "[file summary]",
        f"path: {path}",
        f"size: {summary['line_count']} lines, {summary['char_count']} chars",
    ]
    if segment_count > 1:
        lines_out.append(
            f"selected: segment {segment_index}/{segment_count} (lines {selected_start}-{selected_end})"
        )
    else:
        lines_out.append(f"selected: lines {selected_start}-{selected_end}")
    if summary["highlights"]:
        lines_out.append("highlights:")
        lines_out.extend(f"- {item}" for item in summary["highlights"])
    if summary["keywords"]:
        lines_out.append(f"keywords: {', '.join(summary['keywords'])}")
    lines_out.extend(["", "[file content]", numbered])
    if segment_count > 1:
        lines_out.extend(
            [
                "",
                "[next]",
                (
                    f'Use read_file with {{"path": "{path}", "segment": {min(segment_index + 1, segment_count)}, '
                    f'"segment_lines": {segment_lines}}} to continue scanning.'
                ),
                (
                    f'Or request an exact window with {{"path": "{path}", "start_line": {selected_start}, '
                    f'"end_line": {selected_end}}}.'
                ),
            ]
        )

    metadata: dict[str, Any] = {
        "path": path,
        "line_count": total_lines,
        "char_count": len(text),
        "segmented": segment_count > 1,
        "segment_index": segment_index,
        "segment_count": segment_count,
        "segment_lines": segment_lines,
        "segment_start_line": selected_start,
        "segment_end_line": selected_end,
        "explicit_range": explicit_range,
    }
    if segment_index < segment_count:
        metadata["next_segment"] = segment_index + 1
    return "\n".join(lines_out).strip(), metadata


def format_match_listing(
    *,
    label: str,
    query: str,
    hits: list[MatchHit],
    offset: int = 0,
    limit: int = 40,
) -> tuple[str, dict[str, Any]]:
    total = len(hits)
    if total == 0:
        return f"No matches found for: {query}", {"query": query, "total_matches": 0}

    offset = max(0, int(offset or 0))
    limit = max(1, min(int(limit or 40), 200))
    page = hits[offset : offset + limit]
    source_counts = Counter(hit.source for hit in hits)
    summary = ", ".join(f"{name} ({count})" for name, count in source_counts.most_common(5))
    showing_end = offset + len(page)

    lines = [
        f"[{label} summary]",
        f"query: {query}",
        f"total matches: {total} across {len(source_counts)} sources",
        f"showing: {offset + 1}-{showing_end}",
    ]
    if summary:
        lines.append(f"top sources: {summary}")
    lines.extend(["", "[matches]"])
    for index, hit in enumerate(page, start=offset + 1):
        prefix = f"{index}. {hit.source}"
        if hit.line_number is not None:
            prefix += f":{hit.line_number}"
        lines.append(f"{prefix}: {hit.text}")
    if showing_end < total:
        lines.extend(
            [
                "",
                "[next]",
                f"Use offset={showing_end} and limit={limit} to continue from the next page.",
            ]
        )
    metadata: dict[str, Any] = {
        "query": query,
        "total_matches": total,
        "offset": offset,
        "limit": limit,
        "returned_matches": len(page),
        "segmented": total > limit,
    }
    if showing_end < total:
        metadata["next_offset"] = showing_end
    return "\n".join(lines).strip(), metadata


def context_safe_output(text: str, *, limit: int = 4000) -> tuple[str, dict[str, Any]]:
    if len(text) <= limit:
        return text, {}

    summary = summarize_text_block(text, max_highlights=3, max_keywords=5)
    header = [
        "[tool output summary]",
        f"size: {summary['line_count']} lines, {summary['char_count']} chars",
    ]
    if summary["highlights"]:
        header.append("highlights:")
        header.extend(f"- {item}" for item in summary["highlights"])
    if summary["keywords"]:
        header.append(f"keywords: {', '.join(summary['keywords'])}")

    reserved = sum(len(line) + 1 for line in header) + 160
    preview_budget = max(900, limit - reserved)
    preview = _preview_text(text, budget=preview_budget)
    output = "\n".join(
        [
            *header,
            "",
            "[preview]",
            preview,
            "",
            f"...[truncated for context: summarized {len(text)} chars into a compact preview]...",
        ]
    ).strip()
    metadata = {
        "truncated_for_context": True,
        "full_output_chars": len(text),
        "full_output_lines": summary["line_count"],
        "preview_mode": "summary_plus_excerpt",
    }
    return output, metadata


def _highlight_lines(lines: list[str], *, max_items: int) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if any(pattern.search(stripped) for pattern in _HIGHLIGHT_PATTERNS):
            item = f"line {line_number}: {_compact_line(stripped)}"
            if item in seen:
                continue
            items.append(item)
            seen.add(item)
        if len(items) >= max_items:
            return items

    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        item = f"line {line_number}: {_compact_line(stripped)}"
        if item in seen:
            continue
        items.append(item)
        if len(items) >= max_items:
            break
    return items


def _top_keywords(text: str, *, max_items: int) -> list[str]:
    counts: Counter[str] = Counter()
    for token in re.findall(r"[A-Za-z_][A-Za-z0-9_:-]{2,}", text.lower()):
        if token in _STOPWORDS:
            continue
        counts[token] += 1
    return [item for item, _count in counts.most_common(max_items)]


def _compact_line(line: str, *, width: int = 96) -> str:
    if len(line) <= width:
        return line
    return line[: width - 3].rstrip() + "..."


def _numbered_lines(lines: list[str], *, start_line: int) -> str:
    if not lines:
        return "(empty file)"
    width = len(str(start_line + len(lines) - 1))
    return "\n".join(f"{start_line + index:>{width}} | {line}" for index, line in enumerate(lines))


def _preview_text(text: str, *, budget: int) -> str:
    lines = text.splitlines()
    if len(lines) >= 20:
        head_count = max(4, min(10, len(lines) // 8))
        tail_count = head_count
        head = lines[:head_count]
        tail = lines[-tail_count:]
        preview = "\n".join(["[head]", *head, "", "[tail]", *tail])
        if len(preview) <= budget:
            return preview
    head_budget = max(300, budget // 2)
    tail_budget = max(220, budget - head_budget - 48)
    head = text[:head_budget].rstrip()
    tail = text[-tail_budget:].lstrip() if tail_budget < len(text) else ""
    if tail:
        return f"{head}\n\n[... omitted middle content ...]\n\n{tail}"
    return head
