---
description: Read-only repository inspection workflow
argument-hint: Inspection target
allowed-tools: workspace_status,list_registry,tool_help,skill,read_file,grep,glob,read_json
---

# Read-Only Inspect

Target: $ARGUMENTS

Use only read-only tools while investigating.

## Workflow

1. Check local instructions and ecosystem inventory first.
2. Search broadly before drilling into files.
3. Load a relevant skill if one appears useful.
4. Summarize concrete findings, risks, and likely next edits without changing files.
