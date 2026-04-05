---
name: command-authoring
description: Write markdown commands that constrain workflows cleanly and remain usable in repeated terminal sessions.
---

# Command Authoring

Use this skill when creating or revising `.claude/commands/*.md`.

- keep the command short enough to run repeatedly in chat
- define the workflow in order: inspect, narrow scope, act, validate, summarize
- use `allowed-tools` to encode the safe lane instead of relying on prose alone
- include at least one recovery step when the first path is blocked
- if a command is read-only, tell the model what to do when the user asks for mutation anyway
- commands should package repeatable work, not duplicate the entire system prompt

