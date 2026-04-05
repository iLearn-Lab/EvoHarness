---
name: validation-gating
description: Turn proposed harness changes into candidate-first changes with explicit replay, regression, and rollback expectations.
---

# Validation Gating

Use this skill when a change affects commands, skills, or self-evolution flow.

- candidate first, promotion second
- record the smallest replay step that proves the original failure or success pattern
- record the narrowest regression command that guards the touched behavior
- keep rollback possible until the next healthy run
- do not claim the harness evolved safely unless replay, regression, and rollback expectations are explicit

