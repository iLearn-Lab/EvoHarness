---
name: long-context-retrieval
description: Read large files and broad search results progressively instead of blowing up the live context window.
---

# Long Context Retrieval

Use this skill when the task needs large-file reading, deep codebase explanation, or long search sessions.

- start with `workspace_status` or `list_registry` only once, then narrow down
- prefer `grep` before `read_file` when you do not yet know the exact window
- for large files, read the first segment, then request the next exact segment instead of re-reading the whole file
- if the tool shows `next segment` or `next offset`, follow that pointer instead of restarting the scan
- stop after enough evidence is collected and summarize; do not keep exploring just because more files exist
- when the model starts looping on exploration, switch from discovery to explanation

