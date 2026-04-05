---
name: mcp-service-design
description: Design MCP servers that expose tools, resources, and prompts the harness will actually reuse.
---

# MCP Service Design

- Expose tools for actions, resources for durable reference material, and prompts for repeatable briefs.
- Keep schemas narrow enough that the model can call them reliably without guessing.
- Make local stdio servers workspace-aware so they read the right repo, sessions, and settings.
- Include registry metadata in `mcp.json` so the home surface is informative even before first use.
- Validate `tools/list`, `resources/list`, and `prompts/list` instead of assuming one successful boot is enough.

