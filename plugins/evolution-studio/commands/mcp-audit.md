---
description: Audit whether MCP coverage is strong enough for the current harness workflow
argument-hint: Audit focus
allowed-tools: workspace_status,list_registry,tool_help,skill,mcp_registry_detail,mcp_call_tool,mcp_read_resource,mcp_get_prompt,read_file,grep,glob
---

# MCP Audit

Focus: $ARGUMENTS

## Workflow

1. Load `mcp-first-discovery` first.
2. Inspect MCP servers, tools, resources, and prompts.
3. Compare current MCP coverage with the workflow the user actually wants.
4. Report what MCP already solves and what should be added next.
