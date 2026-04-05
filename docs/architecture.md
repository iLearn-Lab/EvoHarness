# Architecture

## Position in the stack

Evo Harness is not the runtime itself.
It lives one layer above the runtime:

```text
Model + Tools + Runtime Harness
            |
            v
Workspace / Trace / Capability Surface
            |
            v
Evo Harness Control Plane
```

This makes the project portable across harnesses.

## Inputs

Evo Harness consumes three things:

- **Trace**: what happened during one task
- **Capabilities**: what the harness is allowed and able to mutate
- **Workspace snapshot**: what durable artifacts exist in the current project

## Outputs

The output is an evolution plan:

- operator
- rationale
- validation plan
- change request
- safe-to-apply flag

Operators can now target more than just skills and memory:

- revise a skill,
- revise a command workflow,
- distill persistent memory,
- or stop safely.

## Why workspace discovery matters

This project intentionally treats files like:

- `CLAUDE.md`
- `MEMORY.md`
- `.openharness/skills/*.md`
- `.claude/hooks/*.json`
- `.mcp.json`

as real evolution surfaces.

That follows the harness engineering direction made popular by Claude Code and made more explicit in OpenHarness.

The runtime prompt and registry layers intentionally surface these assets back to the model so the query loop can reason over commands, agents, plugins, and guardrails directly.

That now includes MCP-native server, tool, resource, and prompt registries loaded from settings, workspace files, and plugins.

## Why validation is built in

A useful self-evolution system must know when **not** to mutate.
That is why validation planning is part of the core architecture instead of an optional add-on.
