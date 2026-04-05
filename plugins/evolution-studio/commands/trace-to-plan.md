---
description: Turn a real session trace into an evolution recommendation with engineering-value framing
argument-hint: Session or failure pattern
allowed-tools: workspace_status,list_registry,tool_help,skill,read_file,grep,glob,read_json,run_subagent
---

# Trace To Plan

Target: $ARGUMENTS

## Workflow

1. Load `self-evolution-triage` and `trace-driven-commands` when relevant.
2. Inspect the trace, nearby commands, and nearby skills.
3. Prefer the smallest mutation that improves future engineering throughput.
4. State whether the best action is stop, memory, command, or skill.

