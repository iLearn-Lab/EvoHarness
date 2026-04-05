---
name: registry-hygiene
description: Keep the command, agent, skill, plugin, and MCP registry coherent as the harness grows.
---

# Registry Hygiene

- Watch for near-duplicate commands that differ only by wording.
- Make sure agent tool allowlists match the job they are meant to do.
- Include static MCP metadata in `.mcp.json` so discovery is useful before first tool call.
- If an asset cannot be found from the registry surface, improve the packaging before adding more.

