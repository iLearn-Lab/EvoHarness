from __future__ import annotations

import json
import sys
from typing import Any

from evo_harness.harness.web_research import fetch_page_text, run_web_search


PROTOCOL_VERSION = "2025-06-18"


def _handle_method(method: str, params: dict[str, Any]) -> dict[str, Any]:
	if method == "initialize":
		return {
			"protocolVersion": PROTOCOL_VERSION,
			"serverInfo": {"name": "web-research", "version": "0.1.0"},
			"capabilities": {"tools": {}, "resources": {}, "prompts": {}},
		}
	if method == "tools/list":
		return {
			"tools": [
				{
					"name": "search_web",
					"description": "Search the public web. Uses Tavily when TAVILY_API_KEY is set, otherwise falls back to configured MCP search.",
					"inputSchema": {
						"type": "object",
						"properties": {
							"query": {"type": "string"},
							"max_results": {"type": "integer"},
						},
						"required": ["query"],
						"additionalProperties": False,
					},
				},
				{
					"name": "fetch_page",
					"description": "Fetch one web page and return compact readable text.",
					"inputSchema": {
						"type": "object",
						"properties": {
							"url": {"type": "string"},
							"max_chars": {"type": "integer"},
						},
						"required": ["url"],
						"additionalProperties": False,
					},
				},
			]
		}
	if method == "tools/call":
		name = str(params.get("name", ""))
		arguments = dict(params.get("arguments", {}) or {})
		if name == "search_web":
			query = str(arguments.get("query", "")).strip()
			response = run_web_search(query, max_results=int(arguments.get("max_results", 5)))
			return {
				"content": [{"type": "text", "text": response.formatted_text}],
				"metadata": {
					"query": query,
					"result_count": len(response.results),
					"provider": response.provider,
					**dict(response.metadata),
				},
			}
		if name == "fetch_page":
			url = str(arguments.get("url", "")).strip()
			text = fetch_page_text(url, max_chars=int(arguments.get("max_chars", 8000)))
			return {"content": [{"type": "text", "text": text}]}
		raise ValueError(f"Unknown tool: {name}")
	if method == "prompts/list":
		return {
			"prompts": [
				{
					"name": "web_research_brief",
					"description": "Turn a topic into a focused web-research plan.",
					"arguments": [{"name": "topic", "description": "Topic to research", "required": True}],
				}
			]
		}
	if method == "prompts/get":
		name = str(params.get("name", ""))
		if name != "web_research_brief":
			raise ValueError(f"Unknown prompt: {name}")
		arguments = dict(params.get("arguments", {}) or {})
		topic = str(arguments.get("topic", "")).strip() or "the requested topic"
		return {
			"description": "Web research brief",
			"messages": [
				{
					"role": "user",
					"content": [
						{
							"type": "text",
							"text": (
								f"Research {topic} on the public web.\n"
								"- Search first, then fetch only the most relevant pages.\n"
								"- Summarize the result with links, tradeoffs, and the best next step."
							),
						}
					],
				}
			],
		}
	if method == "resources/list":
		return {"resources": []}
	if method == "notifications/initialized":
		return {}
	raise ValueError(f"Unsupported MCP method: {method}")


def _read_message() -> dict[str, Any] | None:
	headers: dict[str, str] = {}
	while True:
		line = sys.stdin.buffer.readline()
		if not line:
			return None
		if line == b"\r\n":
			break
		key, value = line.decode("ascii").split(":", 1)
		headers[key.strip().lower()] = value.strip()
	length = int(headers.get("content-length", "0"))
	body = sys.stdin.buffer.read(length)
	return json.loads(body.decode("utf-8"))


def _write_message(payload: dict[str, Any]) -> None:
	body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
	header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
	sys.stdout.buffer.write(header + body)
	sys.stdout.buffer.flush()


def main() -> None:
	while True:
		message = _read_message()
		if message is None:
			return
		method = str(message.get("method", ""))
		request_id = message.get("id")
		try:
			result = _handle_method(method, dict(message.get("params", {}) or {}))
			if request_id is not None:
				_write_message({"jsonrpc": "2.0", "id": request_id, "result": result})
		except Exception as exc:
			if request_id is not None:
				_write_message({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}})


if __name__ == "__main__":
	main()
