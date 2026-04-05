# Project Instructions

- This repository builds EvoHarness itself, so prefer changes that improve the real harness surface rather than only the narrative docs.
- Keep `src/evo_harness/`, `.claude/`, `plugins/`, and `.evo-harness/` aligned when adding workflow features.
- Prefer focused patches over broad rewrites, especially in `src/evo_harness/harness/`.
- When touching provider or terminal behavior, validate both the Python path and the React terminal path.
- Preserve Windows compatibility and UTF-8 behavior across Python, Node, and terminal boundaries.
- When improving ecosystem features, favor real workspace assets in this repo over placeholder examples.

## Validation

- Python compile smoke: `python -m compileall src`
- Runtime smoke: `evoh doctor --workspace .`
- Registry smoke: `evoh mcp-list --workspace . --kind all`
- Terminal frontend typecheck: `cd frontend/terminal && npm exec -- tsc --noEmit`
- Live provider smoke bench: `python scripts/live_workbench.py --provider moonshot --model kimi-k2.5 --api-key-env MOONSHOT_API_KEY`

## Local Notes

- The public GitHub release intentionally omits tests, examples, caches, and generated runtime state.
- The actual user-facing workspace is this repo root.
- If skills, commands, agents, plugins, or MCP feel absent, add them here so the live harness can really expose them.
- Self-evolution quality depends on archived sessions, workspace instructions, and reusable memories being present.
