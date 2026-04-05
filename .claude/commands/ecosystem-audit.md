---
description: Audit the live harness ecosystem and verify discoverability
argument-hint: Audit focus
allowed-tools: workspace_status,list_registry,tool_help,skill,render_command,mcp_registry_detail,mcp_call_tool,mcp_read_resource,mcp_get_prompt,read_file,grep,glob,read_json
---

# Ecosystem Audit

Focus: $ARGUMENTS

## Goals

1. Enumerate skills, commands, agents, plugins, and MCP assets.
2. Verify which ones are actually available in this workspace.
3. Load the most relevant skill instructions rather than assuming them.
4. Report missing or shallow areas that keep the harness behind Claude Code or OpenHarness.
