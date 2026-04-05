---
description: Research a topic on the public web and summarize the strongest sources
argument-hint: Research topic
allowed-tools: web_search,web_fetch,tool_help,skill,mcp_call_tool,mcp_get_prompt,run_subagent
---

# Web Research

Topic: $ARGUMENTS

## Workflow

1. Load the `web-research` skill first.
2. Search the public web before fetching pages.
3. Fetch only the best few sources.
4. If useful, delegate one bounded pass to `web-scout`.
5. Summarize results with links and the best next step.
