---
description: Diagnose Kimi, GLM, and other live-provider compatibility failures
argument-hint: Failure symptom
allowed-tools: workspace_status,list_registry,tool_help,skill,read_file,grep,glob,read_json,run_subagent
---

# Provider Diagnose

Symptom: $ARGUMENTS

## Workflow

1. Load `live-provider-debugging` before changing anything.
2. Inspect provider conversion, query compaction, and the failing transcript path.
3. If the failure is subtle, delegate a bounded pass to `provider-debugger`.
4. Summarize the exact compatibility rule and the smallest safe patch.

