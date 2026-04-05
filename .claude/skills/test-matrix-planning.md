---
name: test-matrix-planning
description: Turn a growing harness surface into a realistic verification matrix instead of a few lucky spot checks.
---

# Test Matrix Planning

- Cover discovery, rendering, invocation, and failure paths for each surface.
- Prefer tests that iterate the live registry over tests that hardcode yesterday's counts.
- Separate metadata validation from real runtime interaction so failures are easier to localize.
- When the surface grows, grow the verification harness with it.

