from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from evo_harness.harness.plugins import load_workspace_plugins
from evo_harness.harness.settings import HarnessSettings, load_settings


@dataclass(slots=True)
class McpToolDefinition:
    server: str
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    source: str = "settings"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class McpResourceDefinition:
    server: str
    uri: str
    name: str = ""
    description: str = ""
    mime_type: str = ""
    source: str = "settings"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class McpPromptDefinition:
    server: str
    name: str
    description: str = ""
    arguments: list[dict[str, Any]] = field(default_factory=list)
    source: str = "settings"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class McpServerDefinition:
    name: str
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    source: str = "settings"
    description: str = ""
    tools: list[McpToolDefinition] = field(default_factory=list)
    resources: list[McpResourceDefinition] = field(default_factory=list)
    prompts: list[McpPromptDefinition] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "transport": self.transport,
            "command": self.command,
            "args": list(self.args),
            "url": self.url,
            "env": dict(self.env),
            "headers": dict(self.headers),
            "source": self.source,
            "description": self.description,
            "tools": [item.to_dict() for item in self.tools],
            "resources": [item.to_dict() for item in self.resources],
            "prompts": [item.to_dict() for item in self.prompts],
        }


@dataclass(slots=True)
class McpRegistry:
    servers: list[McpServerDefinition]

    def to_dict(self) -> dict[str, Any]:
        return {
            "servers": [server.to_dict() for server in self.servers],
            "tools": [tool.to_dict() for tool in self.tools()],
            "resources": [resource.to_dict() for resource in self.resources()],
            "prompts": [prompt.to_dict() for prompt in self.prompts()],
        }

    def tools(self) -> list[McpToolDefinition]:
        return [tool for server in self.servers for tool in server.tools]

    def resources(self) -> list[McpResourceDefinition]:
        return [resource for server in self.servers for resource in server.resources]

    def prompts(self) -> list[McpPromptDefinition]:
        return [prompt for server in self.servers for prompt in server.prompts]


def load_mcp_registry(workspace: str | Path, settings: HarnessSettings | None = None) -> McpRegistry:
    root = Path(workspace).resolve()
    settings = settings or load_settings(workspace=root)
    servers_by_name: dict[str, McpServerDefinition] = {}

    for name, payload in settings.mcp_servers.items():
        servers_by_name[name] = _server_from_payload(name, payload, source="settings")

    for path, source in _mcp_source_files(root):
        if not path.exists():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        for name, payload in dict(raw.get("mcpServers", raw.get("servers", {}))).items():
            servers_by_name[name] = _merge_server(servers_by_name.get(name), _server_from_payload(name, payload, source=source))

    for plugin in load_workspace_plugins(root, settings=settings):
        plugin_root = Path(plugin.path)
        mcp_file = plugin_root / plugin.manifest.mcp_file
        if not mcp_file.exists():
            continue
        raw = json.loads(mcp_file.read_text(encoding="utf-8"))
        for name, payload in dict(raw.get("mcpServers", raw.get("servers", {}))).items():
            key = f"{plugin.manifest.name}:{name}"
            servers_by_name[key] = _merge_server(
                servers_by_name.get(key),
                _server_from_payload(key, payload, source=f"plugin:{plugin.manifest.name}"),
            )

    return McpRegistry(servers=sorted(servers_by_name.values(), key=lambda item: item.name))


def list_mcp_servers(workspace: str | Path, settings: HarnessSettings | None = None) -> list[dict[str, Any]]:
    return [server.to_dict() for server in load_mcp_registry(workspace, settings=settings).servers]


def list_mcp_tools(workspace: str | Path, settings: HarnessSettings | None = None) -> list[dict[str, Any]]:
    return [tool.to_dict() for tool in load_mcp_registry(workspace, settings=settings).tools()]


def list_mcp_resources(workspace: str | Path, settings: HarnessSettings | None = None) -> list[dict[str, Any]]:
    return [resource.to_dict() for resource in load_mcp_registry(workspace, settings=settings).resources()]


def list_mcp_prompts(workspace: str | Path, settings: HarnessSettings | None = None) -> list[dict[str, Any]]:
    return [prompt.to_dict() for prompt in load_mcp_registry(workspace, settings=settings).prompts()]


def _mcp_source_files(root: Path) -> list[tuple[Path, str]]:
    return [
        (root / ".mcp.json", "workspace"),
        (root / ".evo-harness" / "mcp.json", "evo-harness"),
        (root / ".openharness" / "mcp.json", "openharness"),
    ]


def _server_from_payload(name: str, payload: dict[str, Any], *, source: str) -> McpServerDefinition:
    tools = [
        McpToolDefinition(
            server=name,
            name=str(item["name"]),
            description=str(item.get("description", "")),
            input_schema=dict(item.get("input_schema", {})),
            source=source,
        )
        for item in payload.get("tools", [])
        if isinstance(item, dict) and item.get("name")
    ]
    resources = [
        McpResourceDefinition(
            server=name,
            uri=str(item["uri"]),
            name=str(item.get("name", "")),
            description=str(item.get("description", "")),
            mime_type=str(item.get("mime_type", item.get("mimeType", ""))),
            source=source,
        )
        for item in payload.get("resources", [])
        if isinstance(item, dict) and item.get("uri")
    ]
    prompts = [
        McpPromptDefinition(
            server=name,
            name=str(item["name"]),
            description=str(item.get("description", "")),
            arguments=list(item.get("arguments", [])),
            source=source,
        )
        for item in payload.get("prompts", [])
        if isinstance(item, dict) and item.get("name")
    ]
    return McpServerDefinition(
        name=name,
        transport=str(payload.get("transport", "stdio")),
        command=payload.get("command"),
        args=[str(item) for item in payload.get("args", [])],
        url=payload.get("url"),
        env={str(key): str(value) for key, value in dict(payload.get("env", {})).items()},
        headers={str(key): str(value) for key, value in dict(payload.get("headers", {})).items()},
        source=source,
        description=str(payload.get("description", "")),
        tools=tools,
        resources=resources,
        prompts=prompts,
    )


def _merge_server(existing: McpServerDefinition | None, incoming: McpServerDefinition) -> McpServerDefinition:
    if existing is None:
        return incoming
    merged = McpServerDefinition(
        name=incoming.name,
        transport=incoming.transport or existing.transport,
        command=incoming.command or existing.command,
        args=incoming.args or existing.args,
        url=incoming.url or existing.url,
        env={**existing.env, **incoming.env},
        headers={**existing.headers, **incoming.headers},
        source=incoming.source,
        description=incoming.description or existing.description,
        tools=_merge_named_items(existing.tools, incoming.tools, key=lambda item: item.name),
        resources=_merge_named_items(existing.resources, incoming.resources, key=lambda item: item.uri),
        prompts=_merge_named_items(existing.prompts, incoming.prompts, key=lambda item: item.name),
    )
    return merged


def _merge_named_items(existing: list[Any], incoming: list[Any], *, key) -> list[Any]:
    merged: dict[str, Any] = {str(key(item)): item for item in existing}
    for item in incoming:
        merged[str(key(item))] = item
    return sorted(merged.values(), key=lambda item: str(key(item)))
