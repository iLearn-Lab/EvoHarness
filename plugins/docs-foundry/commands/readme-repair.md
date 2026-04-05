---
description: Repair README drift against the live harness surface
argument-hint: README focus area
allowed-tools: workspace_status,list_registry,mcp_registry_detail,tool_help,skill,mcp_call_tool,mcp_read_resource,read_file,grep,glob,run_subagent
---

# README Repair

Focus: $ARGUMENTS

1. Load `readme-repair` first.
2. Compare README claims with the live registry and visible plugins.
3. If useful, delegate one bounded pass to `readme-auditor`.
4. End with the highest-leverage README fixes.

