---
description: Audit replay, regression, and rollback gates before promoting an evolution candidate
argument-hint: Candidate or workflow
allowed-tools: workspace_status,list_registry,tool_help,skill,read_file,grep,glob,read_json,task_control
---

# Validation Gate

Candidate: $ARGUMENTS

## Workflow

1. Load `validation-gating` first.
2. Inspect replay, regression, rollback, and promotion policy surfaces.
3. If needed, delegate a bounded review to `validation-guardian`.
4. Conclude with what is safe now, what is blocked, and what evidence is missing.
