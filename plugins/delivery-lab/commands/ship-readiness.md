---
description: Review whether a candidate or workflow is truly ready to ship
argument-hint: Candidate or workflow
allowed-tools: workspace_status,list_registry,mcp_registry_detail,tool_help,skill,mcp_call_tool,mcp_read_resource,mcp_get_prompt,read_file,grep,glob,run_subagent
---

# Ship Readiness

Target: $ARGUMENTS

1. Load `release-readiness` first.
2. Use `delivery-lab:quality-gate` to pull doctor, promotion, and session evidence.
3. If useful, delegate one bounded review to `release-coordinator`.
4. Finish with go/no-go, blockers, and the next smallest safe step.

