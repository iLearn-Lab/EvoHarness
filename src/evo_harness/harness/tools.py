from __future__ import annotations

import json
import re
import subprocess
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from evo_harness.harness.content_windows import MatchHit, context_safe_output, format_match_listing, format_segmented_file_view


@dataclass(slots=True)
class ToolExecutionContext:
    cwd: Path
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    output: str
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BaseTool(ABC):
    name: str
    description: str
    category: str = "general"
    tags: tuple[str, ...] = ()
    source: str = "builtin"
    destructive: bool = False
    default_read_only: bool = False
    parallel_safe: bool = True
    aliases: tuple[str, ...] = ()

    @abstractmethod
    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        raise NotImplementedError

    def is_read_only(self, arguments: dict[str, Any]) -> bool:
        del arguments
        return self.default_read_only

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema(),
            "category": self.category,
            "tags": list(self.tags),
            "source": self.source,
            "destructive": self.destructive,
            "aliases": list(self.aliases),
            "read_only": self.default_read_only,
            "parallel_safe": self.parallel_safe,
        }

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "additionalProperties": True}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._aliases: dict[str, str] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool
        for alias in tool.aliases:
            self._aliases[alias] = tool.name

    def get(self, name: str) -> BaseTool | None:
        canonical = self._aliases.get(name, name)
        return self._tools.get(canonical)

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return [tool.name for tool in self.list_tools()]

    def describe(self) -> list[dict[str, Any]]:
        return [tool.describe() for tool in sorted(self.list_tools(), key=lambda item: item.name)]

    def search(self, query: str | None = None, *, category: str | None = None) -> list[dict[str, Any]]:
        query_text = (query or "").strip().lower()
        results: list[dict[str, Any]] = []
        for tool in sorted(self.list_tools(), key=lambda item: item.name):
            description = tool.describe()
            if category and description["category"] != category:
                continue
            if not query_text:
                results.append(description)
                continue
            haystack = " ".join(
                [
                    description["name"],
                    description["description"],
                    description["category"],
                    " ".join(description["tags"]),
                    " ".join(description["aliases"]),
                ]
            ).lower()
            if query_text in haystack:
                results.append(description)
        return results

    def filtered(self, allowed_names: list[str] | None) -> "ToolRegistry":
        registry = ToolRegistry()
        allowed = set(allowed_names or [])
        for tool in self.list_tools():
            if not allowed_names or tool.name in allowed or allowed.intersection(set(tool.aliases)):
                registry.register(tool)
        return registry


class ReadFileTool(BaseTool):
    name = "read_file"
    aliases = ("file_read",)
    description = (
        "Read a text file from the workspace. Large files are automatically summarized and chunked; "
        "use segment or start_line/end_line to continue reading."
    )
    category = "filesystem"
    tags = ("read", "file", "workspace")
    default_read_only = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        path = _resolve_path(context.cwd, arguments["path"])
        if not path.exists():
            return ToolResult(output=f"File not found: {path}", is_error=True)
        text = path.read_text(encoding="utf-8", errors="replace")
        rendered, metadata = format_segmented_file_view(
            path=_display_path(path, context.cwd),
            text=text,
            start_line=int(arguments["start_line"]) if "start_line" in arguments else None,
            end_line=int(arguments["end_line"]) if "end_line" in arguments else None,
            segment=int(arguments["segment"]) if "segment" in arguments else None,
            segment_lines=int(arguments.get("segment_lines", 120)),
        )
        return ToolResult(output=rendered, metadata=metadata)

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path."},
                "start_line": {"type": "integer", "description": "Optional 1-based start line for an exact window."},
                "end_line": {"type": "integer", "description": "Optional 1-based inclusive end line for an exact window."},
                "segment": {
                    "type": "integer",
                    "description": "Optional 1-based chunk index for large files when reading progressively.",
                },
                "segment_lines": {
                    "type": "integer",
                    "description": "Approximate number of lines per chunk when segment is used.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        }


class WriteFileTool(BaseTool):
    name = "write_file"
    aliases = ("file_write",)
    description = "Write or append text content into a workspace file."
    category = "filesystem"
    tags = ("write", "file", "workspace")
    destructive = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        path = _resolve_path(context.cwd, arguments["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = arguments.get("mode", "overwrite")
        content = str(arguments.get("content", ""))
        previous_exists = path.exists()
        previous_text = path.read_text(encoding="utf-8", errors="replace") if previous_exists else None
        if mode == "append":
            with path.open("a", encoding="utf-8") as handle:
                handle.write(content)
        else:
            path.write_text(content, encoding="utf-8")
        metadata = {"path": str(path), "previous_exists": previous_exists}
        if previous_text is not None:
            metadata["previous_text"] = previous_text
        return ToolResult(output=f"Wrote {len(content)} chars to {path}", metadata=metadata)

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "mode": {"type": "string", "enum": ["overwrite", "append"]},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        }


class BashTool(BaseTool):
    name = "bash"
    aliases = ("run_command", "shell")
    description = "Run one shell command inside the workspace."
    category = "execution"
    tags = ("shell", "command", "process")
    destructive = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        command = str(arguments["command"])
        timeout = int(arguments.get("timeout_ms", 30000)) / 1000.0
        shell_command = _shell_command(command)
        cwd = _resolve_optional_path(context.cwd, arguments.get("cwd"))
        try:
            process = subprocess.run(
                shell_command,
                cwd=str(cwd),
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(output=f"Command timed out after {timeout:.1f}s", is_error=True)
        output = "\n".join(part for part in [process.stdout.strip(), process.stderr.strip()] if part)
        return ToolResult(
            output=output or "(no output)",
            is_error=process.returncode != 0,
            metadata={"returncode": process.returncode, "cwd": str(cwd)},
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout_ms": {"type": "integer"},
            },
            "required": ["command"],
            "additionalProperties": False,
        }


class GlobTool(BaseTool):
    name = "glob"
    description = "Find files matching a glob pattern."
    category = "filesystem"
    tags = ("search", "glob", "paths")
    default_read_only = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        pattern = str(arguments["pattern"])
        matches = sorted(str(path) for path in context.cwd.glob(pattern))
        return ToolResult(output="\n".join(matches) if matches else "(no matches)")

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        }


class ListDirTool(BaseTool):
    name = "list_dir"
    description = "List files and directories in a workspace path."
    category = "filesystem"
    tags = ("list", "directory", "workspace")
    default_read_only = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        target = _resolve_path(context.cwd, str(arguments.get("path", ".")))
        if not target.exists():
            return ToolResult(output=f"Path not found: {target}", is_error=True)
        if not target.is_dir():
            return ToolResult(output=f"Not a directory: {target}", is_error=True)
        include_hidden = bool(arguments.get("include_hidden", False))
        entries: list[str] = []
        for path in sorted(target.iterdir(), key=lambda item: item.name.lower()):
            if not include_hidden and path.name.startswith("."):
                continue
            marker = "/" if path.is_dir() else ""
            entries.append(f"{path.name}{marker}")
        return ToolResult(output="\n".join(entries) if entries else "(empty directory)")

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "include_hidden": {"type": "boolean"},
            },
            "additionalProperties": False,
        }


class GrepTool(BaseTool):
    name = "grep"
    description = (
        "Search text across workspace files. Large result sets are automatically summarized and paginated; "
        "use offset and limit to continue."
    )
    category = "search"
    tags = ("search", "regex", "text")
    default_read_only = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        pattern = str(arguments["pattern"])
        glob_pattern = str(arguments.get("glob", "**/*"))
        ignore_case = bool(arguments.get("ignore_case", True))
        flags = re.IGNORECASE if ignore_case else 0
        regex = re.compile(pattern, flags)
        hits: list[MatchHit] = []
        for path in sorted(context.cwd.glob(glob_pattern)):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    hits.append(
                        MatchHit(
                            source=str(path.relative_to(context.cwd)),
                            line_number=lineno,
                            text=line.strip(),
                        )
                    )
        rendered, metadata = format_match_listing(
            label="search",
            query=pattern,
            hits=hits,
            offset=int(arguments.get("offset", 0)),
            limit=int(arguments.get("limit", 40)),
        )
        return ToolResult(output=rendered, metadata=metadata)

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for."},
                "glob": {"type": "string", "description": "Optional glob used to scope matching files."},
                "ignore_case": {"type": "boolean", "description": "Case-insensitive by default."},
                "offset": {"type": "integer", "description": "Skip this many matches before returning results."},
                "limit": {"type": "integer", "description": "Maximum matches to return in one page."},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        }


class ReplaceInFileTool(BaseTool):
    name = "replace_in_file"
    aliases = ("file_edit",)
    description = "Replace exact text in a file."
    category = "filesystem"
    tags = ("edit", "replace", "file")
    destructive = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        path = _resolve_path(context.cwd, arguments["path"])
        if not path.exists():
            return ToolResult(output=f"File not found: {path}", is_error=True)
        old = str(arguments["old"])
        new = str(arguments["new"])
        text = path.read_text(encoding="utf-8", errors="replace")
        count = text.count(old)
        if count == 0:
            return ToolResult(output="No matching text found.", is_error=True)
        if not bool(arguments.get("replace_all", False)) and count > 1:
            return ToolResult(
                output=f"Found {count} matches. Pass replace_all=true to replace all occurrences.",
                is_error=True,
            )
        updated = text.replace(old, new) if bool(arguments.get("replace_all", False)) else text.replace(old, new, 1)
        path.write_text(updated, encoding="utf-8")
        return ToolResult(
            output=f"Updated {path} ({count if bool(arguments.get('replace_all', False)) else 1} replacement(s)).",
            metadata={"path": str(path), "previous_text": text},
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old": {"type": "string"},
                "new": {"type": "string"},
                "replace_all": {"type": "boolean"},
            },
            "required": ["path", "old", "new"],
            "additionalProperties": False,
        }


class TodoWriteTool(BaseTool):
    name = "todo_write"
    description = "Persist a small todo list for the current workspace."
    category = "coordination"
    tags = ("todo", "plan", "workspace")
    destructive = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        todos = arguments.get("todos", [])
        if not isinstance(todos, list):
            return ToolResult(output="todos must be a list.", is_error=True)
        path = context.cwd / ".evo-harness" / "todos.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = []
        for item in todos:
            if isinstance(item, dict):
                payload.append(
                    {
                        "task": str(item.get("task", "")),
                        "status": str(item.get("status", "pending")),
                    }
                )
            else:
                payload.append({"task": str(item), "status": "pending"})
        previous_text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else None
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        metadata = {"path": str(path)}
        if previous_text is not None:
            metadata["previous_text"] = previous_text
        return ToolResult(output=f"Wrote {len(payload)} todo items to {path}", metadata=metadata)

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": {"type": ["string", "object"]},
                }
            },
            "required": ["todos"],
            "additionalProperties": False,
        }


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = "Fetch text content from one URL."
    category = "web"
    tags = ("web", "fetch", "http")
    default_read_only = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        del context
        import urllib.request

        url = str(arguments["url"])
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                content = response.read().decode("utf-8", errors="replace")
        except Exception as exc:
            return ToolResult(output=f"Fetch failed: {exc}", is_error=True)
        max_chars = int(arguments.get("max_chars", 8000))
        if len(content) > max_chars:
            content, metadata = context_safe_output(content, limit=max_chars)
            return ToolResult(output=content, metadata=metadata)
        return ToolResult(output=content)

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "max_chars": {"type": "integer"},
            },
            "required": ["url"],
            "additionalProperties": False,
        }


class WebSearchTool(BaseTool):
    name = "web_search"
    description = "Search the web and return compact top results with titles, URLs, and snippets."
    category = "web"
    tags = ("web", "search", "research")
    default_read_only = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        del context
        from evo_harness.harness.web_research import format_web_search_results, search_web

        query = str(arguments["query"]).strip()
        if not query:
            return ToolResult(output="query must be non-empty.", is_error=True)
        try:
            results = search_web(query, max_results=int(arguments.get("max_results", 5)))
        except Exception as exc:
            return ToolResult(output=f"Web search failed: {exc}", is_error=True)
        return ToolResult(
            output=format_web_search_results(query, results),
            metadata={"query": query, "result_count": len(results)},
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["query"],
            "additionalProperties": False,
        }


class ReadJsonTool(BaseTool):
    name = "read_json"
    description = "Read a JSON file and pretty-print it."
    category = "filesystem"
    tags = ("json", "read", "file")
    default_read_only = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        path = _resolve_path(context.cwd, arguments["path"])
        if not path.exists():
            return ToolResult(output=f"File not found: {path}", is_error=True)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return ToolResult(output=f"Invalid JSON: {exc}", is_error=True)
        return ToolResult(output=json.dumps(data, indent=2, ensure_ascii=False))

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        }


class WriteJsonTool(BaseTool):
    name = "write_json"
    description = "Write a JSON object to a file."
    category = "filesystem"
    tags = ("json", "write", "file")
    destructive = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        path = _resolve_path(context.cwd, arguments["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        data = arguments["data"]
        previous_text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else None
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        metadata = {"path": str(path)}
        if previous_text is not None:
            metadata["previous_text"] = previous_text
        return ToolResult(output=f"Wrote JSON to {path}", metadata=metadata)

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "data": {"type": ["object", "array", "string", "number", "boolean", "null"]},
            },
            "required": ["path", "data"],
            "additionalProperties": False,
        }


class MakeDirTool(BaseTool):
    name = "make_dir"
    description = "Create a directory if it does not already exist."
    category = "filesystem"
    tags = ("mkdir", "directory", "workspace")
    destructive = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        path = _resolve_path(context.cwd, arguments["path"])
        existed = path.exists()
        path.mkdir(parents=bool(arguments.get("parents", True)), exist_ok=True)
        return ToolResult(output=f"Ensured directory exists: {path}", metadata={"path": str(path), "previous_exists": existed})

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "parents": {"type": "boolean"},
            },
            "required": ["path"],
            "additionalProperties": False,
        }


class DeletePathTool(BaseTool):
    name = "delete_path"
    description = "Delete a file or empty directory."
    category = "filesystem"
    tags = ("delete", "file", "directory")
    destructive = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        path = _resolve_path(context.cwd, arguments["path"])
        if not path.exists():
            return ToolResult(output=f"Path not found: {path}", is_error=True)
        if path.is_dir():
            path.rmdir()
            return ToolResult(output=f"Removed directory: {path}", metadata={"path": str(path), "kind": "directory"})
        previous_text = path.read_text(encoding="utf-8", errors="replace")
        path.unlink()
        return ToolResult(
            output=f"Removed file: {path}",
            metadata={"path": str(path), "kind": "file", "previous_text": previous_text},
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        }


class ListRegistryTool(BaseTool):
    name = "list_registry"
    description = "List runtime registry items such as tools, commands, agents, plugins, tasks, or sessions."
    category = "runtime"
    tags = ("registry", "commands", "agents", "plugins", "tools")
    default_read_only = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        kind = str(arguments.get("kind", "tools"))
        query = str(arguments.get("query", "")).strip().lower()
        runtime = _runtime_from_context(context)
        if runtime is None:
            return ToolResult(output="Runtime metadata is unavailable.", is_error=True)

        if kind == "tools":
            payload = runtime.tool_registry.search(query or None)
        elif kind == "commands":
            payload = _filter_items(runtime.list_commands(), query)
        elif kind == "agents":
            payload = _filter_items(runtime.list_agents(), query)
        elif kind == "plugins":
            payload = _filter_items(runtime.list_plugins(), query)
        elif kind == "mcp_servers":
            payload = _filter_items(runtime.list_mcp_servers(), query)
        elif kind == "mcp_tools":
            payload = _filter_items(runtime.list_mcp_tools(), query)
        elif kind == "mcp_resources":
            payload = _filter_items(runtime.list_mcp_resources(), query)
        elif kind == "mcp_prompts":
            payload = _filter_items(runtime.list_mcp_prompts(), query)
        elif kind == "tasks":
            payload = _filter_items(runtime.list_tasks(), query)
        elif kind == "sessions":
            payload = _filter_items(runtime.list_sessions(), query)
        elif kind == "all":
            payload = {
                "tools": runtime.tool_registry.search(query or None),
                "commands": _filter_items(runtime.list_commands(), query),
                "agents": _filter_items(runtime.list_agents(), query),
                "plugins": _filter_items(runtime.list_plugins(), query),
                "mcp_servers": _filter_items(runtime.list_mcp_servers(), query),
                "mcp_tools": _filter_items(runtime.list_mcp_tools(), query),
                "mcp_resources": _filter_items(runtime.list_mcp_resources(), query),
                "mcp_prompts": _filter_items(runtime.list_mcp_prompts(), query),
                "tasks": _filter_items(runtime.list_tasks(), query),
                "sessions": _filter_items(runtime.list_sessions(), query),
            }
        else:
            return ToolResult(output=f"Unknown registry kind: {kind}", is_error=True)
        return ToolResult(output=json.dumps(payload, indent=2, ensure_ascii=False))

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": [
                        "tools",
                        "commands",
                        "agents",
                        "plugins",
                        "mcp_servers",
                        "mcp_tools",
                        "mcp_resources",
                        "mcp_prompts",
                        "tasks",
                        "sessions",
                        "all",
                    ],
                },
                "query": {"type": "string"},
            },
            "additionalProperties": False,
        }


class McpRegistryDetailTool(BaseTool):
    name = "mcp_registry_detail"
    description = "Describe one MCP server, tool, resource, or prompt from the local registry."
    category = "runtime"
    tags = ("mcp", "registry", "detail")
    default_read_only = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        runtime = _runtime_from_context(context)
        if runtime is None:
            return ToolResult(output="Runtime metadata is unavailable.", is_error=True)
        kind = str(arguments["kind"])
        name = str(arguments["name"])
        registry_map = {
            "server": runtime.list_mcp_servers(),
            "tool": runtime.list_mcp_tools(),
            "resource": runtime.list_mcp_resources(),
            "prompt": runtime.list_mcp_prompts(),
        }
        items = registry_map.get(kind)
        if items is None:
            return ToolResult(output=f"Unknown MCP detail kind: {kind}", is_error=True)
        for item in items:
            candidates = [
                str(item.get("name", "")),
                str(item.get("uri", "")),
            ]
            if name in candidates:
                return ToolResult(output=json.dumps(item, indent=2, ensure_ascii=False))
        return ToolResult(output=f"No MCP {kind} found for: {name}", is_error=True)

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["server", "tool", "resource", "prompt"]},
                "name": {"type": "string"},
            },
            "required": ["kind", "name"],
            "additionalProperties": False,
        }


class McpRuntimeCallTool(BaseTool):
    name = "mcp_call_tool"
    description = (
        "Call one MCP tool on a configured MCP server. Prefer this when the registry already exposes "
        "workspace-aware knowledge or actions."
    )
    category = "runtime"
    tags = ("mcp", "tool", "runtime")
    default_read_only = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        runtime = _runtime_from_context(context)
        if runtime is None:
            return ToolResult(output="Runtime metadata is unavailable.", is_error=True)
        from evo_harness.harness.mcp_runtime import call_mcp_tool

        try:
            payload = call_mcp_tool(
                runtime.workspace,
                server_name=str(arguments["server"]),
                tool_name=str(arguments["name"]),
                arguments=dict(arguments.get("arguments", {})),
            )
        except Exception as exc:
            return ToolResult(output=f"MCP tool call failed: {exc}", is_error=True)
        return ToolResult(output=json.dumps(payload, indent=2, ensure_ascii=False))

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "server": {"type": "string"},
                "name": {"type": "string"},
                "arguments": {"type": "object"},
            },
            "required": ["server", "name"],
            "additionalProperties": False,
        }


class McpReadResourceTool(BaseTool):
    name = "mcp_read_resource"
    description = "Read one MCP resource from a configured MCP server instead of re-discovering the same material manually."
    category = "runtime"
    tags = ("mcp", "resource", "runtime")
    default_read_only = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        runtime = _runtime_from_context(context)
        if runtime is None:
            return ToolResult(output="Runtime metadata is unavailable.", is_error=True)
        from evo_harness.harness.mcp_runtime import read_mcp_resource

        try:
            payload = read_mcp_resource(
                runtime.workspace,
                server_name=str(arguments["server"]),
                uri=str(arguments["uri"]),
            )
        except Exception as exc:
            return ToolResult(output=f"MCP resource read failed: {exc}", is_error=True)
        return ToolResult(output=json.dumps(payload, indent=2, ensure_ascii=False))

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "server": {"type": "string"},
                "uri": {"type": "string"},
            },
            "required": ["server", "uri"],
            "additionalProperties": False,
        }


class McpGetPromptTool(BaseTool):
    name = "mcp_get_prompt"
    description = "Fetch one MCP prompt template from a configured MCP server when a purpose-built prompt already exists."
    category = "runtime"
    tags = ("mcp", "prompt", "runtime")
    default_read_only = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        runtime = _runtime_from_context(context)
        if runtime is None:
            return ToolResult(output="Runtime metadata is unavailable.", is_error=True)
        from evo_harness.harness.mcp_runtime import get_mcp_prompt

        try:
            payload = get_mcp_prompt(
                runtime.workspace,
                server_name=str(arguments["server"]),
                prompt_name=str(arguments["name"]),
                arguments=dict(arguments.get("arguments", {})),
            )
        except Exception as exc:
            return ToolResult(output=f"MCP prompt fetch failed: {exc}", is_error=True)
        return ToolResult(output=json.dumps(payload, indent=2, ensure_ascii=False))

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "server": {"type": "string"},
                "name": {"type": "string"},
                "arguments": {"type": "object"},
            },
            "required": ["server", "name"],
            "additionalProperties": False,
        }


class ToolHelpTool(BaseTool):
    name = "tool_help"
    description = "Describe one registered tool in detail."
    category = "runtime"
    tags = ("tool", "registry", "schema")
    default_read_only = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        runtime = _runtime_from_context(context)
        if runtime is None:
            return ToolResult(output="Runtime metadata is unavailable.", is_error=True)
        name = str(arguments["name"])
        tool = runtime.tool_registry.get(name)
        if tool is None:
            return ToolResult(output=f"Unknown tool: {name}", is_error=True)
        return ToolResult(output=json.dumps(tool.describe(), indent=2, ensure_ascii=False))

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        }


class SkillTool(BaseTool):
    name = "skill"
    description = "Load the full markdown instructions for one available skill."
    category = "runtime"
    tags = ("skill", "knowledge", "instructions")
    default_read_only = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        from evo_harness.harness.skills import load_workspace_skills

        requested = str(arguments["name"]).strip()
        if not requested:
            return ToolResult(output="Skill name cannot be empty.", is_error=True)

        lowered = requested.lower()
        for skill in load_workspace_skills(context.cwd):
            if skill.name.lower() == lowered:
                return ToolResult(output=skill.content)
        return ToolResult(output=f"Skill not found: {requested}", is_error=True)

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        }


class RenderCommandTool(BaseTool):
    name = "render_command"
    description = "Render one registered command with optional arguments before improvising a workflow."
    category = "runtime"
    tags = ("command", "render", "workflow")
    default_read_only = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        runtime = _runtime_from_context(context)
        if runtime is None:
            return ToolResult(output="Runtime metadata is unavailable.", is_error=True)
        name = str(arguments["name"])
        arguments_text = str(arguments.get("arguments", ""))
        try:
            rendered = runtime.render_command(name, arguments_text)
        except KeyError:
            return ToolResult(output=f"Command not found: {name}", is_error=True)
        return ToolResult(output=rendered)

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "arguments": {"type": "string"},
            },
            "required": ["name"],
            "additionalProperties": False,
        }


class WorkspaceStatusTool(BaseTool):
    name = "workspace_status"
    description = "Return a concise runtime and ecosystem summary for the current workspace."
    category = "runtime"
    tags = ("workspace", "status", "summary")
    default_read_only = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        del arguments
        runtime = _runtime_from_context(context)
        if runtime is None:
            return ToolResult(output="Runtime metadata is unavailable.", is_error=True)
        settings = runtime.settings
        payload = {
            "workspace": str(runtime.workspace),
            "model": settings.model,
            "provider": {
                "provider": settings.provider.provider,
                "profile": settings.provider.profile,
                "base_url": settings.provider.base_url,
                "api_format": settings.provider.api_format,
            },
            "query": {
                "max_turns": settings.query.max_turns,
                "max_total_tool_calls": settings.query.max_total_tool_calls,
                "max_tool_failures": settings.query.max_tool_failures,
            },
            "safety": {
                "max_mutating_tools_per_query": settings.safety.max_mutating_tools_per_query,
                "blocked_shell_patterns": settings.safety.blocked_shell_patterns,
                "sandbox_mode": settings.sandbox.mode,
                "approval_mode": settings.approvals.mode,
            },
            "counts": {
                "tools": len(runtime.list_tools()),
                "commands": len(runtime.list_commands()),
                "agents": len(runtime.list_agents()),
                "plugins": len(runtime.list_plugins()),
                "approvals_pending": len(runtime.list_approvals(status="pending")),
                "tasks": len(runtime.list_tasks()),
                "sessions": len(runtime.list_sessions()),
            },
            "active_command": runtime.active_command.to_dict() if runtime.active_command is not None else None,
        }
        return ToolResult(output=json.dumps(payload, indent=2, ensure_ascii=False))


class RunSubagentTool(BaseTool):
    name = "run_subagent"
    description = (
        "Delegate one bounded exploration, review, or comparison task to a registered subagent. "
        "Prefer this for focused parallel inspection."
    )
    category = "runtime"
    tags = ("subagent", "delegation", "agent")
    destructive = False
    default_read_only = True
    parallel_safe = False

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        runtime = _runtime_from_context(context)
        if runtime is None:
            return ToolResult(output="Runtime metadata is unavailable.", is_error=True)
        provider_factory = context.metadata.get("provider_factory")
        if not callable(provider_factory):
            return ToolResult(output="No provider factory is active for subagent execution.", is_error=True)
        agent = runtime.get_agent(str(arguments["name"]))
        if agent is None:
            return ToolResult(output=f"Agent not found: {arguments['name']}", is_error=True)
        from evo_harness.harness.subagents import run_subagent

        result = run_subagent(
            runtime,
            agent=agent,
            task=str(arguments["task"]),
            provider=provider_factory(),
            max_turns=int(arguments.get("max_turns", runtime.settings.subagents.default_max_turns)),
        )
        payload = result.to_dict()
        return ToolResult(
            output=json.dumps(payload, indent=2, ensure_ascii=False),
            metadata={
                "agent_name": payload.get("agent_name"),
                "turn_count": payload.get("turn_count"),
                "tool_count": payload.get("tool_count"),
                "stop_reason": payload.get("stop_reason"),
                "summary": payload.get("summary"),
                "tool_names": payload.get("tool_names"),
                "model_name": payload.get("model_name"),
                "session_path": payload.get("session_path"),
            },
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Registered agent name."},
                "task": {"type": "string", "description": "Bounded task delegated to the subagent."},
                "max_turns": {"type": "integer", "description": "Optional turn cap for this subagent run."},
            },
            "required": ["name", "task"],
            "additionalProperties": False,
        }


class TaskControlTool(BaseTool):
    name = "task_control"
    description = "Create, inspect, wait for, or stop background tasks."
    category = "coordination"
    tags = ("task", "background", "automation")
    destructive = True

    def is_read_only(self, arguments: dict[str, Any]) -> bool:
        return str(arguments.get("action", "")).lower() in {"list", "get", "output", "wait"}

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        runtime = _runtime_from_context(context)
        if runtime is None:
            return ToolResult(output="Runtime metadata is unavailable.", is_error=True)
        from evo_harness.harness.tasks import get_task_manager

        task_manager = get_task_manager(runtime.workspace)
        action = str(arguments["action"])
        try:
            if action == "list":
                payload = [item.to_dict() for item in task_manager.list_tasks(status=arguments.get("status"))]
            elif action == "create_shell":
                record = task_manager.create_shell_task(
                    command=str(arguments["command"]),
                    description=str(arguments.get("description", "background task")),
                )
                payload = record.to_dict()
            elif action == "get":
                record = task_manager.get_task(str(arguments["id"]))
                if record is None:
                    return ToolResult(output=f"Task not found: {arguments['id']}", is_error=True)
                payload = record.to_dict()
            elif action == "output":
                payload = {
                    "id": str(arguments["id"]),
                    "output": task_manager.read_task_output(str(arguments["id"]), max_bytes=int(arguments.get("max_bytes", 12000))),
                }
            elif action == "wait":
                record = task_manager.wait_task(str(arguments["id"]), timeout_s=float(arguments.get("timeout_s", 30.0)))
                payload = record.to_dict()
            elif action == "stop":
                payload = task_manager.stop_task(str(arguments["id"])).to_dict()
            else:
                return ToolResult(output=f"Unknown task action: {action}", is_error=True)
        except Exception as exc:
            return ToolResult(output=f"Task action failed: {exc}", is_error=True)
        return ToolResult(output=json.dumps(payload, indent=2, ensure_ascii=False))

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "create_shell", "get", "output", "wait", "stop"],
                },
                "id": {"type": "string"},
                "status": {"type": "string"},
                "command": {"type": "string"},
                "description": {"type": "string"},
                "max_bytes": {"type": "integer"},
                "timeout_s": {"type": "number"},
            },
            "required": ["action"],
            "additionalProperties": False,
        }


class SessionAnalyticsTool(BaseTool):
    name = "session_analytics"
    description = "Summarize archived session behavior for the current workspace."
    category = "runtime"
    tags = ("session", "analytics", "history")
    default_read_only = True

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        runtime = _runtime_from_context(context)
        if runtime is None:
            return ToolResult(output="Runtime metadata is unavailable.", is_error=True)
        from evo_harness.harness.session import session_analytics_report

        payload = session_analytics_report(runtime.workspace, limit=int(arguments.get("limit", 50)))
        return ToolResult(output=json.dumps(payload, indent=2, ensure_ascii=False))

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
            "additionalProperties": False,
        }


class ApprovalControlTool(BaseTool):
    name = "approval_control"
    description = "Inspect or decide queued approval requests."
    category = "runtime"
    tags = ("approval", "permissions", "queue")
    destructive = True

    def is_read_only(self, arguments: dict[str, Any]) -> bool:
        return str(arguments.get("action", "")).lower() == "list"

    def execute(self, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolResult:
        runtime = _runtime_from_context(context)
        if runtime is None:
            return ToolResult(output="Runtime metadata is unavailable.", is_error=True)
        action = str(arguments["action"])
        try:
            if action == "list":
                payload = runtime.list_approvals(status=arguments.get("status"))
            elif action in {"approve", "deny"}:
                request = runtime.approval_manager.decide(
                    str(arguments["id"]),
                    approved=action == "approve",
                    note=str(arguments.get("note", "")),
                )
                payload = request.to_dict()
            else:
                return ToolResult(output=f"Unknown approval action: {action}", is_error=True)
        except Exception as exc:
            return ToolResult(output=f"Approval action failed: {exc}", is_error=True)
        return ToolResult(output=json.dumps(payload, indent=2, ensure_ascii=False))

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "approve", "deny"]},
                "status": {"type": "string"},
                "id": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["action"],
            "additionalProperties": False,
        }


def create_default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in (
        ReadFileTool(),
        WriteFileTool(),
        BashTool(),
        GlobTool(),
        ListDirTool(),
        GrepTool(),
        ReplaceInFileTool(),
        TodoWriteTool(),
        WebSearchTool(),
        WebFetchTool(),
        ReadJsonTool(),
        WriteJsonTool(),
        MakeDirTool(),
        DeletePathTool(),
        ListRegistryTool(),
        McpRegistryDetailTool(),
        McpRuntimeCallTool(),
        McpReadResourceTool(),
        McpGetPromptTool(),
        ToolHelpTool(),
        SkillTool(),
        RenderCommandTool(),
        WorkspaceStatusTool(),
        RunSubagentTool(),
        TaskControlTool(),
        SessionAnalyticsTool(),
    ):
        registry.register(tool)
    return registry


def _resolve_path(cwd: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = cwd / path
    return path.resolve()


def _resolve_optional_path(cwd: Path, raw_path: Any) -> Path:
    if isinstance(raw_path, str) and raw_path.strip():
        return _resolve_path(cwd, raw_path)
    return cwd


def _display_path(path: Path, cwd: Path) -> str:
    try:
        return str(path.relative_to(cwd))
    except ValueError:
        return str(path)


def _shell_command(command: str) -> list[str]:
    if Path("C:/Windows").exists():
        return ["powershell", "-NoProfile", "-Command", command]
    return ["/bin/bash", "-lc", command]


def _runtime_from_context(context: ToolExecutionContext):
    return context.metadata.get("runtime")


def _filter_items(items: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    if not query:
        return items
    lowered = query.lower()
    results: list[dict[str, Any]] = []
    for item in items:
        haystack = json.dumps(item, ensure_ascii=False).lower()
        if lowered in haystack:
            results.append(item)
    return results
