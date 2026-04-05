from __future__ import annotations

from html import unescape
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
import re
import urllib.request


def search_web(query: str, *, max_results: int = 5) -> list[dict[str, str]]:
	query_text = query.strip()
	if not query_text:
		return []
	url = f"https://html.duckduckgo.com/html/?q={quote_plus(query_text)}"
	request = urllib.request.Request(
		url,
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
	lines = [f"[web search]", f"query: {query}", ""]
	for index, item in enumerate(results, start=1):
		lines.append(f"{index}. {item['title']}")
		lines.append(f"   {item['url']}")
		if item.get("snippet"):
			lines.append(f"   {item['snippet']}")
		lines.append("")
	return "\n".join(lines).strip()


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
