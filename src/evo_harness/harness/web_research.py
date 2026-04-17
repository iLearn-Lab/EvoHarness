from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from evo_harness.harness.mcp import McpServerDefinition
from evo_harness.harness.settings import HarnessSettings, SearchSettings, load_settings


@dataclass(slots=True)
class WebSearchResponse:
    query: str
    results: list[dict[str, str]]
    provider: str
    formatted_text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def run_web_search(
    query: str,
    *,
    max_results: int = 5,
    workspace: str | Path | None = None,
    settings: HarnessSettings | None = None,
) -> WebSearchResponse:
    query_text = query.strip()
    if not query_text:
        return WebSearchResponse(
            query="",
            results=[],
            provider="none",
            formatted_text="No web results found for an empty query.",
        )

    resolved_workspace = _resolve_workspace(workspace)
    resolved_settings = settings
    if resolved_settings is None and resolved_workspace is not None:
        resolved_settings = load_settings(workspace=resolved_workspace)

    search_settings = resolved_settings.search if resolved_settings is not None else SearchSettings()
    limit = max(1, min(int(max_results), 10))
    tavily_api_key = _resolve_tavily_api_key(search_settings)
    if tavily_api_key:
        results = _search_via_tavily(
            query_text,
            max_results=limit,
            api_key=tavily_api_key,
            base_url=search_settings.tavily_base_url,
        )
        return WebSearchResponse(
            query=query_text,
            results=results,
            provider="tavily",
            formatted_text=format_web_search_results(query_text, results),
            metadata={"provider": "tavily", "result_count": len(results)},
        )

    exa_error: Exception | None = None
    if search_settings.fallback_to_exa:
        try:
            return _search_via_exa_mcp(
                query_text,
                max_results=limit,
                workspace=resolved_workspace or Path.cwd(),
                search_settings=search_settings,
            )
        except Exception as exc:
            exa_error = exc

    mcp_error: Exception | None = None
    if search_settings.fallback_to_mcp:
        if resolved_workspace is not None:
            try:
                return _search_via_mcp(
                    query_text,
                    max_results=limit,
                    workspace=resolved_workspace,
                    settings=resolved_settings,
                    search_settings=search_settings,
                )
            except Exception as exc:
                mcp_error = exc
        else:
            mcp_error = ValueError("No workspace is available for MCP search fallback.")
    else:
        mcp_error = ValueError("MCP fallback is disabled.")

    if search_settings.fallback_to_builtin:
        results = _search_via_duckduckgo_html(query_text, max_results=limit)
        metadata = {"provider": "builtin:duckduckgo-html", "result_count": len(results)}
        if exa_error is not None:
            metadata["exa_fallback_error"] = str(exa_error)
        if mcp_error is not None:
            metadata["mcp_fallback_error"] = str(mcp_error)
        return WebSearchResponse(
            query=query_text,
            results=results,
            provider="builtin:duckduckgo-html",
            formatted_text=format_web_search_results(query_text, results),
            metadata=metadata,
        )

    if mcp_error is not None:
        raise mcp_error
    raise ValueError("No Tavily API key is configured and all fallback search paths are disabled.")


def search_web(
    query: str,
    *,
    max_results: int = 5,
    workspace: str | Path | None = None,
    settings: HarnessSettings | None = None,
) -> list[dict[str, str]]:
    return run_web_search(
        query,
        max_results=max_results,
        workspace=workspace,
        settings=settings,
    ).results


def fetch_page_text(url: str, *, max_chars: int = 8000) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; EvoHarness/0.1; +https://example.invalid)",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        content = response.read().decode("utf-8", errors="replace")
    text = _clean_html(content)
    return text[:max_chars]


def format_web_search_results(query: str, results: list[dict[str, str]]) -> str:
    if not results:
        return f"No web results found for: {query}"
    lines = ["[web search]", f"query: {query}", ""]
    for index, item in enumerate(results, start=1):
        lines.append(f"{index}. {item['title']}")
        lines.append(f"   {item['url']}")
        if item.get("snippet"):
            lines.append(f"   {item['snippet']}")
        lines.append("")
    return "\n".join(lines).strip()


def _resolve_workspace(workspace: str | Path | None) -> Path | None:
    if workspace is not None:
        return Path(workspace).resolve()
    env_workspace = str(os.environ.get("EVO_HARNESS_WORKSPACE", "") or "").strip()
    if env_workspace:
        return Path(env_workspace).resolve()
    return None


def _resolve_tavily_api_key(search_settings: SearchSettings) -> str:
    return _resolve_optional_env_key(search_settings.tavily_api_key, search_settings.tavily_api_key_env)


def _resolve_optional_env_key(direct_value: str | None, env_name: str | None) -> str:
    direct_key = str(direct_value or "").strip()
    if direct_key:
        return direct_key
    env_text = str(env_name or "").strip()
    if not env_text:
        return ""
    return str(os.environ.get(env_text, "") or "").strip()


def _search_via_tavily(query: str, *, max_results: int, api_key: str, base_url: str) -> list[dict[str, str]]:
    payload = {
        "query": query,
        "search_depth": "basic",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
    }
    response = _post_json(
        str(base_url or "https://api.tavily.com/search").strip() or "https://api.tavily.com/search",
        payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    return _normalize_search_results(response.get("results", []))


def _search_via_duckduckgo_html(query: str, *, max_results: int) -> list[dict[str, str]]:
    request = urllib.request.Request(
        f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; EvoHarness/0.1; +https://example.invalid)",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        html = response.read().decode("utf-8", errors="replace")

    link_matches = list(
        re.finditer(
            r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )
    results: list[dict[str, str]] = []
    for match in link_matches[: max(1, min(max_results, 10))]:
        title = _clean_html(match.group("title"))
        href = _resolve_duckduckgo_link(match.group("href"))
        window = html[match.end() : match.end() + 1200]
        snippet_match = re.search(
            r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>|<div[^>]+class="result__snippet"[^>]*>(?P<divsnippet>.*?)</div>',
            window,
            flags=re.IGNORECASE | re.DOTALL,
        )
        snippet = ""
        if snippet_match:
            snippet = _clean_html(snippet_match.group("snippet") or snippet_match.group("divsnippet") or "")
        results.append(
            {
                "title": title or "(untitled result)",
                "url": href,
                "snippet": snippet,
            }
        )
    return results


def _search_via_exa_mcp(
    query: str,
    *,
    max_results: int,
    workspace: Path,
    search_settings: SearchSettings,
) -> WebSearchResponse:
    from evo_harness.harness.mcp_runtime import call_mcp_tool_with_server

    headers: dict[str, str] = {}
    exa_api_key = _resolve_optional_env_key(search_settings.exa_api_key, search_settings.exa_api_key_env)
    if exa_api_key:
        headers["Authorization"] = f"Bearer {exa_api_key}"
    server = McpServerDefinition(
        name="exa-remote",
        transport="streamable-http",
        url=str(search_settings.exa_mcp_url or "https://mcp.exa.ai/mcp?tools=web_search_exa"),
        headers=headers,
    )
    payload = call_mcp_tool_with_server(
        workspace,
        server=server,
        tool_name="web_search_exa",
        arguments={"query": query, "numResults": max_results},
    )
    response = _response_from_mcp_payload(
        query,
        payload,
        provider="mcp:exa-remote/web_search_exa",
        server_name="exa-remote",
        tool_name="web_search_exa",
    )
    response.metadata.setdefault("result_count", len(response.results))
    return response


def _search_via_mcp(
    query: str,
    *,
    max_results: int,
    workspace: Path,
    settings: HarnessSettings | None,
    search_settings: SearchSettings,
) -> WebSearchResponse:
    from evo_harness.harness.mcp import load_mcp_registry
    from evo_harness.harness.mcp_runtime import call_mcp_tool

    registry = load_mcp_registry(workspace, settings=settings)
    server_name, tool_name, input_schema = _resolve_mcp_search_target(registry, search_settings)
    arguments = _build_mcp_search_arguments(
        query,
        max_results=max_results,
        input_schema=input_schema,
        search_settings=search_settings,
    )
    payload = call_mcp_tool(
        workspace,
        server_name=server_name,
        tool_name=tool_name,
        arguments=arguments,
    )
    response = _response_from_mcp_payload(
        query,
        payload,
        provider=f"mcp:{server_name}/{tool_name}",
        server_name=server_name,
        tool_name=tool_name,
    )
    response.metadata.setdefault("result_count", len(response.results))
    return response


def _resolve_mcp_search_target(registry: Any, search_settings: SearchSettings) -> tuple[str, str, dict[str, Any]]:
    server_by_name = {server.name: server for server in registry.servers}
    explicit_server = str(search_settings.mcp_server or "").strip()
    explicit_tool = str(search_settings.mcp_tool or "").strip()

    if explicit_server:
        server = server_by_name.get(explicit_server)
        if server is None:
            raise ValueError(f"Configured MCP search server was not found: {explicit_server}")
        return _pick_search_tool_for_server(server, requested_tool=explicit_tool or None)

    if explicit_tool:
        matches: list[tuple[str, str, dict[str, Any], int]] = []
        for server in registry.servers:
            for tool in server.tools:
                if tool.name != explicit_tool:
                    continue
                if _is_recursive_builtin_search_target(server, tool.name):
                    continue
                matches.append((server.name, tool.name, dict(tool.input_schema or {}), _search_tool_score(server, tool)))
        if not matches:
            raise ValueError(f"Configured MCP search tool was not found: {explicit_tool}")
        matches.sort(key=lambda item: item[3], reverse=True)
        return matches[0][0], matches[0][1], matches[0][2]

    ranked: list[tuple[int, str, str, dict[str, Any]]] = []
    for server in registry.servers:
        for tool in server.tools:
            score = _search_tool_score(server, tool)
            if score < 0:
                continue
            if _is_recursive_builtin_search_target(server, tool.name):
                continue
            ranked.append((score, server.name, tool.name, dict(tool.input_schema or {})))
    if not ranked:
        raise ValueError("No MCP web-search target was found. Configure search.mcp_server/search.mcp_tool or set TAVILY_API_KEY.")
    ranked.sort(reverse=True)
    _score, server_name, tool_name, input_schema = ranked[0]
    return server_name, tool_name, input_schema


def _pick_search_tool_for_server(server: Any, *, requested_tool: str | None) -> tuple[str, str, dict[str, Any]]:
    if requested_tool:
        tool = next((item for item in server.tools if item.name == requested_tool), None)
        if tool is None:
            raise ValueError(f"Configured MCP search tool was not found on server {server.name}: {requested_tool}")
        if _is_recursive_builtin_search_target(server, tool.name):
            raise ValueError("Configured MCP search target points to the built-in web-research server and would recurse.")
        return server.name, tool.name, dict(tool.input_schema or {})

    ranked: list[tuple[int, str, str, dict[str, Any]]] = []
    for tool in server.tools:
        score = _search_tool_score(server, tool)
        if score < 0 or _is_recursive_builtin_search_target(server, tool.name):
            continue
        ranked.append((score, server.name, tool.name, dict(tool.input_schema or {})))
    if not ranked:
        raise ValueError(f"No usable MCP web-search tool was found on server {server.name}.")
    ranked.sort(reverse=True)
    _score, server_name, tool_name, input_schema = ranked[0]
    return server_name, tool_name, input_schema


def _is_recursive_builtin_search_target(server: Any, tool_name: str) -> bool:
    if tool_name not in {"search_web", "web_search"}:
        return False
    command = str(getattr(server, "command", "") or "").lower()
    args = [str(item).lower() for item in getattr(server, "args", [])]
    if "evo_harness.web_research_mcp_server" in command:
        return True
    return any("evo_harness.web_research_mcp_server" in item for item in args)


def _search_tool_score(server: Any, tool: Any) -> int:
    server_name = str(server.name or "")
    tool_name = str(tool.name or "")
    description = str(getattr(tool, "description", "") or "")
    tool_haystack = " ".join([tool_name, description]).lower()
    haystack = " ".join([server_name, tool_name, description]).lower()
    if "search" not in tool_haystack:
        return -1
    looks_like_web_search = any(keyword in haystack for keyword in ("web", "internet", "public web", "tavily"))
    canonical_search_name = tool_name.lower() in {"search_web", "web_search", "tavily-search", "tavily_search"}
    if not looks_like_web_search and not canonical_search_name:
        return -1

    score = 0
    if "tavily" in haystack:
        score += 100
    if tool_name.lower() in {"tavily-search", "tavily_search"}:
        score += 100
    if any(keyword in haystack for keyword in ("web", "internet", "public web")):
        score += 40
    if tool_name.lower() in {"search_web", "web_search", "search"}:
        score += 30
    if "docs" in haystack and not any(keyword in haystack for keyword in ("web", "internet", "tavily")):
        score -= 50
    if "workspace" in haystack and "web" not in haystack:
        score -= 50
    if "session" in haystack:
        score -= 50
    if "catalog" in haystack:
        score -= 50

    return score if score > 0 else -1


def _build_mcp_search_arguments(
    query: str,
    *,
    max_results: int,
    input_schema: dict[str, Any],
    search_settings: SearchSettings,
) -> dict[str, Any]:
    query_key = str(search_settings.mcp_query_argument or "").strip()
    max_results_key = str(search_settings.mcp_max_results_argument or "").strip()
    properties = dict(input_schema.get("properties", {})) if isinstance(input_schema, dict) else {}

    if not query_key:
        for candidate in ("query", "q", "search_query", "text", "topic"):
            if candidate in properties:
                query_key = candidate
                break
    if not query_key:
        query_key = "query"

    if not max_results_key:
        for candidate in ("max_results", "limit", "num_results", "num", "top_k"):
            if candidate in properties:
                max_results_key = candidate
                break

    arguments: dict[str, Any] = {query_key: query}
    if max_results_key:
        arguments[max_results_key] = max_results
    return arguments


def _response_from_mcp_payload(
    query: str,
    payload: dict[str, Any],
    *,
    provider: str,
    server_name: str,
    tool_name: str,
) -> WebSearchResponse:
    results = _normalize_search_results(payload.get("results", []))
    if not results:
        structured = payload.get("structuredContent")
        if isinstance(structured, dict):
            results = _normalize_search_results(structured.get("results", []))

    content_text = _extract_mcp_content_text(payload)
    if not results and content_text:
        parsed = _try_parse_json_block(content_text)
        if isinstance(parsed, dict):
            results = _normalize_search_results(parsed.get("results", []))
        elif isinstance(parsed, list):
            results = _normalize_search_results(parsed)
        if not results:
            results = _parse_formatted_search_text(content_text)

    formatted_text = content_text or format_web_search_results(query, results)
    if not formatted_text.strip():
        raise ValueError(f"MCP search target {server_name}/{tool_name} returned no usable content.")

    return WebSearchResponse(
        query=query,
        results=results,
        provider=provider,
        formatted_text=formatted_text,
        metadata={
            "provider": provider,
            "server": server_name,
            "tool": tool_name,
        },
    )


def _extract_mcp_content_text(payload: dict[str, Any]) -> str:
    blocks = payload.get("content", [])
    if not isinstance(blocks, list):
        return ""
    texts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if str(block.get("type", "")) != "text":
            continue
        text = str(block.get("text", "") or "").strip()
        if text:
            texts.append(text)
    return "\n\n".join(texts).strip()


def _normalize_search_results(items: Any) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("name") or "(untitled result)").strip()
        url = str(item.get("url") or item.get("href") or item.get("link") or "").strip()
        snippet = str(
            item.get("snippet")
            or item.get("content")
            or item.get("description")
            or item.get("text")
            or ""
        ).strip()
        if not url and not snippet and title == "(untitled result)":
            continue
        normalized.append(
            {
                "title": title,
                "url": url,
                "snippet": snippet,
            }
        )
    return normalized


def _parse_formatted_search_text(text: str) -> list[dict[str, str]]:
    blocks = [block.strip() for block in re.split(r"\n\s*---\s*\n", text) if block.strip()]
    results: list[dict[str, str]] = []
    for block in blocks:
        title = ""
        url = ""
        snippet_lines: list[str] = []
        in_highlights = False
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("Title: "):
                title = line[len("Title: ") :].strip()
                continue
            if line.startswith("URL: "):
                url = line[len("URL: ") :].strip()
                continue
            if line == "Highlights:":
                in_highlights = True
                continue
            if line.startswith(("Published: ", "Author: ")):
                continue
            if in_highlights:
                snippet_lines.append(line)
        if title or url:
            results.append(
                {
                    "title": title or "(untitled result)",
                    "url": url,
                    "snippet": " ".join(snippet_lines[:4]).strip(),
                }
            )
    return results


def _try_parse_json_block(text: str) -> Any:
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _post_json(url: str, payload: dict[str, Any], *, headers: dict[str, str]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValueError(detail or f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(str(exc)) from exc


def _resolve_duckduckgo_link(href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    if "duckduckgo.com/l/?" in href:
        parsed = urlparse(href)
        query = parse_qs(parsed.query)
        if "uddg" in query and query["uddg"]:
            return unquote(query["uddg"][0])
    return unescape(href)


def _clean_html(value: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
