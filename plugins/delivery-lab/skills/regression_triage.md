---
name: regression-triage
description: Triage repeated failures by separating product regressions, workflow gaps, and thin validation coverage.
---

# Regression Triage

- Look for repeated failure shapes across sessions, not just the latest run.
- Distinguish missing tests from missing commands, missing skills, or weak MCP support.
- Prefer one high-confidence regression category over a long list of guesses.
- End with the smallest next validation or workflow patch.

