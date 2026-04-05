---
description: Scan the workspace for recent regression patterns and the best next containment move
argument-hint: Failure area or symptom
allowed-tools: workspace_status,list_registry,mcp_registry_detail,tool_help,skill,mcp_call_tool,mcp_read_resource,read_file,grep,glob,run_subagent
---

# Regression Scan

Symptom: $ARGUMENTS

1. Load `regression-triage` first.
2. Inspect doctor and session evidence before blaming code blindly.
3. If the pattern is fuzzy, delegate one bounded pass to `regression-scout`.
4. End with the most likely regression lane and the next containment move.

