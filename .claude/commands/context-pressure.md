---
description: Diagnose long-search, large-file, and context-window pressure in a live session
argument-hint: Pressure source
allowed-tools: workspace_status,list_registry,tool_help,skill,read_file,grep,glob,read_json,run_subagent
---

# Context Pressure

Target: $ARGUMENTS

## Workflow

1. Load `long-context-retrieval` first.
2. Inspect the relevant large files or broad search surfaces progressively.
3. If the space is still large, delegate one bounded narrowing pass to `context-curator`.
4. End with the smallest continuation window instead of an endless scan.

