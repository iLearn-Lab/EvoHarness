from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evo_harness.harness.mcp import McpServerDefinition, load_mcp_registry


MCP_PROTOCOL_VERSION = "2025-06-18"


@dataclass(slots=True)
class McpCallResult:
    server: str
    method: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"server": self.server, "method": self.method, "payload": self.payload}


def call_mcp_method(
    workspace: str | Path,
    *,
    server_name: str,
    method: str,
    params: dict[str, Any] | None = None,
) -> McpCallResult:
    workspace_root = Path(workspace).resolve()
    registry = load_mcp_registry(workspace_root)
    server = next((item for item in registry.servers if item.name == server_name), None)
    if server is None:
        raise ValueError(f"MCP server not found: {server_name}")
    payload = _call_server(server, workspace=workspace_root, method=method, params=params or {})
    return McpCallResult(server=server.name, method=method, payload=payload)


def list_mcp_runtime_tools(workspace: str | Path, *, server_name: str) -> dict[str, Any]:
    return call_mcp_method(workspace, server_name=server_name, method="tools/list").payload


def call_mcp_tool(workspace: str | Path, *, server_name: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return call_mcp_method(
        workspace,
        server_name=server_name,
        method="tools/call",
        params={"name": tool_name, "arguments": arguments},
    ).payload


def list_mcp_runtime_resources(workspace: str | Path, *, server_name: str) -> dict[str, Any]:
    return call_mcp_method(workspace, server_name=server_name, method="resources/list").payload


def read_mcp_resource(workspace: str | Path, *, server_name: str, uri: str) -> dict[str, Any]:
    return call_mcp_method(
        workspace,
        server_name=server_name,
        method="resources/read",
        params={"uri": uri},
    ).payload


def list_mcp_runtime_prompts(workspace: str | Path, *, server_name: str) -> dict[str, Any]:
    return call_mcp_method(workspace, server_name=server_name, method="prompts/list").payload


def get_mcp_prompt(
    workspace: str | Path,
    *,
    server_name: str,
    prompt_name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return call_mcp_method(
        workspace,
        server_name=server_name,
        method="prompts/get",
        params={"name": prompt_name, "arguments": arguments or {}},
    ).payload


def _call_server(
    server: McpServerDefinition,
    *,
    workspace: Path,
    method: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    if server.transport == "stdio":
        return _call_stdio_server(server, workspace=workspace, method=method, params=params)
    if server.transport in {"http", "https", "streamable-http"}:
        return _call_http_server(server, method=method, params=params)
    raise ValueError(f"Unsupported MCP transport: {server.transport}")


def _call_stdio_server(
    server: McpServerDefinition,
    *,
    workspace: Path,
    method: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    if not server.command:
        raise ValueError(f"MCP stdio server {server.name} is missing a command")
    env = dict(os.environ)
    src_dir = workspace / "src"
    if src_dir.exists():
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{src_dir}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(src_dir)
        )
    env["EVO_HARNESS_WORKSPACE"] = str(workspace)
    env.update(server.env)
    process = subprocess.Popen(
        [server.command, *server.args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        cwd=str(workspace),
        env=env,
    )
    try:
        session = _StdIoMcpSession(process)
        session.request(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "clientInfo": {"name": "evo-harness", "version": "0.1.0"},
                "capabilities": {},
            },
        )
        session.notify("notifications/initialized", {})
        result = session.request(method, params)
        return dict(result)
    finally:
        with suppress(Exception):
            if process.stdin is not None:
                process.stdin.close()
        with suppress(Exception):
            if process.stdout is not None:
                process.stdout.close()
        with suppress(Exception):
            if process.stderr is not None:
                process.stderr.close()
        with suppress(Exception):
            process.terminate()
        try:
            process.wait(timeout=1)
        except Exception:
            with suppress(Exception):
                process.kill()


def _call_http_server(server: McpServerDefinition, *, method: str, params: dict[str, Any]) -> dict[str, Any]:
    if not server.url:
        raise ValueError(f"MCP HTTP server {server.name} is missing a URL")
    request_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    data = json.dumps(request_payload).encode("utf-8")
    request = urllib.request.Request(
        server.url,
        data=data,
        headers={"content-type": "application/json", **server.headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if "error" in payload:
        raise ValueError(f"MCP server returned an error: {payload['error']}")
    return dict(payload.get("result", {}))


class _StdIoMcpSession:
    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self._process = process
        self._next_id = 1

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._write_message({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        while True:
            message = self._read_message()
            if message.get("id") == request_id:
                if "error" in message:
                    raise ValueError(f"MCP server returned an error: {message['error']}")
                return dict(message.get("result", {}))

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._write_message({"jsonrpc": "2.0", "method": method, "params": params})

    def _write_message(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        assert self._process.stdin is not None
        self._process.stdin.write(header + body)
        self._process.stdin.flush()

    def _read_message(self) -> dict[str, Any]:
        assert self._process.stdout is not None
        headers: dict[str, str] = {}
        while True:
            line = self._process.stdout.readline()
            if not line:
                stderr_text = b""
                if self._process.stderr is not None:
                    stderr_text = self._process.stderr.read() or b""
                raise ValueError(f"MCP stdio server closed the stream. stderr={stderr_text.decode('utf-8', errors='replace')}")
            if line == b"\r\n":
                break
            key, value = line.decode("ascii").split(":", 1)
            headers[key.strip().lower()] = value.strip()
        length = int(headers.get("content-length", "0"))
        body = self._process.stdout.read(length)
        return json.loads(body.decode("utf-8"))
