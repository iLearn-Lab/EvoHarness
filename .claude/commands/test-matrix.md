---
description: Review or expand the verification matrix for the live harness surface
argument-hint: Surface or risk area
allowed-tools: workspace_status,list_registry,mcp_registry_detail,tool_help,skill,read_file,grep,glob,read_json,run_subagent
---

# Test Matrix

Surface: $ARGUMENTS

1. Load `test-matrix-planning` first.
2. Inspect the live registry and current verification coverage.
3. If useful, delegate one bounded pass to `test-matrix-keeper`.
4. End with the next highest-leverage test additions.
