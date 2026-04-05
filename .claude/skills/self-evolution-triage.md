---
name: self-evolution-triage
description: Decide whether a trace should stop, distill memory, revise a command, or revise a skill.
---

# Self Evolution Triage

Use this skill when judging whether Evo should mutate the harness from a real session trace.

- prefer `stop` when the signal is weak, ambiguous, or not yet repeatable
- prefer `distill_memory` when the run succeeded and surfaced a reusable lesson
- prefer `revise_command` when the active command constrained the task or lacked a recovery path
- prefer `revise_skill` when the harness kept exploring, misused tools, stalled under long context, or repeated the wrong workflow
- candidate artifacts should land in `.evo-harness/candidates` before any promotion
- every proposal should justify engineering value: what future turns get shorter, safer, or more reliable

