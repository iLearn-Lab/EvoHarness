---
name: plugin-packaging
description: Package plugin assets so discovery, enable/disable flow, and MCP wiring all stay dependable.
---

# Plugin Packaging

- Keep `plugin.json` honest about what the bundle actually ships.
- Put commands, skills, agents, and MCP under stable folders so loaders stay simple.
- Treat missing MCP boot paths as a packaging bug, not a user problem.
- End with a plugin that can be discovered, explained, and toggled without confusion.

