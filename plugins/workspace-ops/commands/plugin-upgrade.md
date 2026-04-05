---
description: Review or design a plugin bundle that strengthens the workspace ecosystem
argument-hint: Plugin or bundle goal
allowed-tools: workspace_status,list_registry,mcp_registry_detail,tool_help,skill,mcp_call_tool,read_file,grep,glob,read_json,run_subagent
---

# Plugin Upgrade

Target: $ARGUMENTS

1. Load `plugin-packaging` first.
2. Inspect neighboring plugins, registry naming, and MCP packaging.
3. If the bundle boundary is unclear, delegate one bounded pass to `plugin-caretaker`.
4. Finish with the smallest plugin change that makes the surface stronger.

