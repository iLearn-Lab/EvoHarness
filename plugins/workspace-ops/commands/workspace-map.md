---
description: Map the current workspace surface before adding or revising harness assets
argument-hint: Focus area
allowed-tools: workspace_status,list_registry,tool_help,skill,mcp_call_tool,mcp_read_resource,read_file,grep,glob,run_subagent
---

# Workspace Map

Focus: $ARGUMENTS

1. Load `workspace-topology` first.
2. Call `workspace-ops:workspace-intel` for a workspace snapshot or surface search.
3. If useful, delegate one bounded pass to `surface-curator`.
4. End with the clearest next change area, not a giant inventory dump.

