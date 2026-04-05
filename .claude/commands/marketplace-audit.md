---
description: Review plugin coverage and marketplace quality for the current workspace
argument-hint: Category or catalog focus
allowed-tools: workspace_status,list_registry,tool_help,skill,read_file,grep,glob,read_json,run_subagent
---

# Marketplace Audit

Focus: $ARGUMENTS

1. Load `marketplace-curation` first.
2. Inspect installed plugins, marketplace metadata, and any duplication in bundle purpose.
3. If useful, delegate one bounded review to `marketplace-curator`.
4. Recommend the next catalog move that most improves user experience.
