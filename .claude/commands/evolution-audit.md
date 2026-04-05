---
description: Audit how Evo turns real sessions into evolution plans and candidate artifacts
argument-hint: Audit focus
allowed-tools: workspace_status,list_registry,tool_help,skill,render_command,read_file,grep,glob,read_json,run_subagent
---

# Evolution Audit

Focus: $ARGUMENTS

## Workflow

1. Inspect `engine.py`, `core/analyzer.py`, `core/policy.py`, and `harness/evolution_bridge.py`.
2. Load the most relevant self-evolution skill before drawing conclusions.
3. If useful, delegate one bounded review to `evolution-auditor`.
4. Report whether the current operator choice improves future engineering work.
5. Call out where the system is still too conservative or too noisy.

