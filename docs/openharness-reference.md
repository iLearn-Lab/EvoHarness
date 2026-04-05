# Reference Notes

This project intentionally references public artifacts that were copied into the local workspace before the scaffold was written.

## OpenHarness

Local copy:

- `i:/EVO/repo_inspect/OpenHarness`

Key source files referenced:

- `i:/EVO/repo_inspect/OpenHarness/src/openharness/engine/query_engine.py`
- `i:/EVO/repo_inspect/OpenHarness/src/openharness/permissions/checker.py`
- `i:/EVO/repo_inspect/OpenHarness/src/openharness/memory/manager.py`
- `i:/EVO/repo_inspect/OpenHarness/src/openharness/skills/loader.py`
- `i:/EVO/repo_inspect/OpenHarness/src/openharness/hooks/executor.py`
- `i:/EVO/repo_inspect/OpenHarness/src/openharness/prompts/claudemd.py`
- `i:/EVO/repo_inspect/OpenHarness/src/openharness/services/session_storage.py`
- `i:/EVO/repo_inspect/OpenHarness/src/openharness/tasks/manager.py`
- `i:/EVO/repo_inspect/OpenHarness/src/openharness/tools/base.py`
- `i:/EVO/repo_inspect/OpenHarness/src/openharness/config/settings.py`

Ideas adopted into Evo Harness:

- explicit query/runtime loop
- permission-first execution model
- markdown-native memory and skills
- hook-based lifecycle extension
- session persistence
- task and subagent awareness
- settings-driven behavior

## Claude Code

Local copies:

- `i:/EVO/repo_inspect/claude-code`
- `i:/EVO/repo_inspect/claude-code-docs`

Public repo artifacts referenced:

- `i:/EVO/repo_inspect/claude-code/plugins/README.md`
- `i:/EVO/repo_inspect/claude-code/examples/settings/README.md`
- `i:/EVO/repo_inspect/claude-code/.claude/commands/triage-issue.md`
- `i:/EVO/repo_inspect/claude-code/plugins/feature-dev/README.md`

Docs pages copied locally:

- `i:/EVO/repo_inspect/claude-code-docs/overview.html`
- `i:/EVO/repo_inspect/claude-code-docs/settings.html`
- `i:/EVO/repo_inspect/claude-code-docs/memory.html`
- `i:/EVO/repo_inspect/claude-code-docs/hooks.html`
- `i:/EVO/repo_inspect/claude-code-docs/sub-agents.html`
- `i:/EVO/repo_inspect/claude-code-docs/commands.html`
- `i:/EVO/repo_inspect/claude-code-docs/plugins.html`

Ideas adopted into Evo Harness:

- `CLAUDE.md` as a durable project instruction surface
- settings hierarchy and managed safety posture
- hook events as first-class extension points
- slash-command and plugin-oriented workflow packaging
- subagent-aware delegation model
- workspace-native, terminal-first engineering style

## Important boundary

Claude Code's public GitHub repository does not expose the entire runtime core in the same way OpenHarness does.
For that reason, Evo Harness borrows:

- **runtime-core engineering patterns** mostly from OpenHarness
- **workspace conventions and extension patterns** from Claude Code

That split is intentional and reflects the public artifacts actually available on `2026-04-04`.

