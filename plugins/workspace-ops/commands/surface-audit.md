---
description: Audit command, skill, agent, plugin, and MCP coverage for the current workspace
argument-hint: Gap or category
allowed-tools: workspace_status,list_registry,mcp_registry_detail,tool_help,skill,mcp_call_tool,mcp_read_resource,read_file,grep,glob,run_subagent
---

# Surface Audit

Gap: $ARGUMENTS

1. Load `registry-hygiene` first.
2. Inspect the live registry instead of assuming what exists.
3. If the surface is broad, delegate one bounded pass to `asset-locator`.
4. Recommend the next addition or cleanup that improves discoverability most.

