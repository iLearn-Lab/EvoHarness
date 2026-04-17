from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
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
    static_payload = _static_registry_payload(server, method=method)
    if static_payload is not None:
        return McpCallResult(server=server.name, method=method, payload=static_payload)
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


def call_mcp_tool_with_server(
    workspace: str | Path,
    *,
    server: McpServerDefinition,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    workspace_root = Path(workspace).resolve()
    return _call_server(
        server,
        workspace=workspace_root,
        method="tools/call",
        params={"name": tool_name, "arguments": arguments},
    )


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
    pythonpath_entries: list[str] = []
    current_pythonpath = env.get("PYTHONPATH", "")
    if current_pythonpath:
        pythonpath_entries.extend([entry for entry in current_pythonpath.split(os.pathsep) if entry])
    runtime_src_dir = Path(__file__).resolve().parents[2]
    if runtime_src_dir.exists():
        pythonpath_entries.insert(0, str(runtime_src_dir))
    workspace_src_dir = workspace / "src"
    if workspace_src_dir.exists():
        pythonpath_entries.insert(0, str(workspace_src_dir))
    if pythonpath_entries:
        deduped: list[str] = []
        seen: set[str] = set()
        for entry in pythonpath_entries:
            if entry in seen:
                continue
            seen.add(entry)
            deduped.append(entry)
        env["PYTHONPATH"] = os.pathsep.join(deduped)
    env["EVO_HARNESS_WORKSPACE"] = str(workspace)
    env.update(server.env)
    argv = _resolve_stdio_argv(server)
    process = subprocess.Popen(
        argv,
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


def _resolve_stdio_argv(server: McpServerDefinition) -> list[str]:
    if not server.command:
        raise ValueError(f"MCP stdio server {server.name} is missing a command")
    command = str(server.command).strip()
    if not command:
        raise ValueError(f"MCP stdio server {server.name} is missing a command")
    resolved = shutil.which(command) or command
    if os.name == "nt" and Path(resolved).suffix.lower() == ".ps1":
        return [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            resolved,
            *server.args,
        ]
    return [resolved, *server.args]


def _static_registry_payload(server: McpServerDefinition, *, method: str) -> dict[str, Any] | None:
    if method == "tools/list":
        return {
            "tools": [
                {
                    "name": item.name,
                    "description": item.description,
                    "inputSchema": dict(item.input_schema),
                }
                for item in server.tools
            ]
        }
    if method == "resources/list":
        return {
            "resources": [
                {
                    "uri": item.uri,
                    "name": item.name,
                    "description": item.description,
                    "mimeType": item.mime_type,
                }
                for item in server.resources
            ]
        }
    if method == "prompts/list":
        return {
            "prompts": [
                {
                    "name": item.name,
                    "description": item.description,
                    "arguments": list(item.arguments),
                }
                for item in server.prompts
            ]
        }
    return None


def _call_http_server(server: McpServerDefinition, *, method: str, params: dict[str, Any]) -> dict[str, Any]:
    if not server.url:
        raise ValueError(f"MCP HTTP server {server.name} is missing a URL")
    session = _HttpMcpSession(server)
    session.request(
        "initialize",
        {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "clientInfo": {"name": "evo-harness", "version": "0.1.0"},
            "capabilities": {},
        },
    )
    session.notify("notifications/initialized", {})
    return session.request(method, params)


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


class _HttpMcpSession:
    def __init__(self, server: McpServerDefinition) -> None:
        self._server = server
        self._next_id = 1
        self._session_id: str | None = None

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        message = self._post(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        if "error" in message:
            raise ValueError(f"MCP server returned an error: {message['error']}")
        return dict(message.get("result", {}))

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._post(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            },
            expect_response=False,
        )

    def _post(self, payload: dict[str, Any], *, expect_response: bool = True) -> dict[str, Any]:
        assert self._server.url is not None
        request_headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            "mcp-protocol-version": MCP_PROTOCOL_VERSION,
            **self._server.headers,
        }
        if self._session_id:
            request_headers["mcp-session-id"] = self._session_id
        request = urllib.request.Request(
            self._server.url,
            data=json.dumps(payload).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                self._session_id = str(response.headers.get("mcp-session-id", "") or self._session_id or "") or None
                body = response.read().decode("utf-8", errors="replace")
                content_type = str(response.headers.get("content-type", "") or "").lower()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ValueError(detail or f"HTTP Error {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ValueError(str(exc)) from exc

        if not body.strip():
            return {}
        if "text/event-stream" in content_type:
            return _parse_sse_jsonrpc_response(body)
        message = json.loads(body)
        if not isinstance(message, dict):
            raise ValueError(f"Unexpected MCP HTTP response payload: {message!r}")
        if not expect_response and "id" not in message:
            return {}
        return message


def _parse_sse_jsonrpc_response(body: str) -> dict[str, Any]:
    events = body.replace("\r\n", "\n").split("\n\n")
    for event in events:
        data_lines: list[str] = []
        for line in event.splitlines():
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if not data_lines:
            continue
        payload = "\n".join(data_lines).strip()
        if not payload:
            continue
        message = json.loads(payload)
        if isinstance(message, dict):
            return message
    raise ValueError("MCP server returned an empty SSE response")
