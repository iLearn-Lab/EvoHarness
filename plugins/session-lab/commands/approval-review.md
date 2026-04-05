---
description: Review approval pressure and decide whether the workflow or policy needs adjustment
argument-hint: Approval friction
allowed-tools: workspace_status,list_registry,mcp_registry_detail,tool_help,skill,mcp_call_tool,mcp_read_resource,read_file,grep,glob,run_subagent
---

# Approval Review

Friction: $ARGUMENTS

1. Load `approval-flow` first.
2. Inspect pending approvals before changing policy assumptions.
3. If useful, delegate one bounded pass to `approval-shepherd`.
4. End with the smallest healthy adjustment.

