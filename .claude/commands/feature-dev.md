---
description: Guided feature and bugfix workflow for Evo Harness itself
argument-hint: Feature request or bug
allowed-tools: workspace_status,list_registry,tool_help,skill,read_file,grep,glob,bash,write_file,replace_in_file,read_json,write_json,todo_write,task_control
---

# Feature Development

Request: $ARGUMENTS

## Workflow

1. Inspect `CLAUDE.md` and relevant tests first.
2. Use `workspace_status`, `list_registry`, and `tool_help` to discover the current harness surface area.
3. If a matching skill exists, load it with the `skill` tool before editing.
4. Search nearby implementation and validation patterns before changing behavior.
5. Keep edits focused and validate the smallest useful slice.
6. Summarize risks, remaining gaps, and whether live-provider testing was performed.
