---
description: Shape a user-facing workflow bundle across commands, skills, agents, plugins, and MCP
argument-hint: Workflow goal
allowed-tools: workspace_status,list_registry,mcp_registry_detail,tool_help,skill,read_file,grep,glob,read_json,run_subagent
---

# Workflow Blueprint

Goal: $ARGUMENTS

1. Load `workflow-bundling` first.
2. Inspect which assets already support the workflow.
3. If useful, delegate one bounded pass to `workflow-gardener`.
4. End with the leanest complete bundle worth shipping.

