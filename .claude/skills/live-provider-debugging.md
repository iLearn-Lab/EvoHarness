---
name: live-provider-debugging
description: Diagnose provider compatibility issues such as invalid message shapes, reasoning-content mismatches, and long-turn stalls.
---

# Live Provider Debugging

Use this skill when Kimi, GLM, or another live provider returns malformed-request or empty-turn behavior.

- inspect the exact provider profile, base URL, and model first
- compare the failing session shape with what the provider expects: assistant tool calls, tool results, and reasoning metadata
- treat `messages 参数非法`, missing `tool_call_id`, or repeated empty assistant turns as provider-compatibility signals, not just random flakiness
- check whether the transcript was compacted in a way that broke tool-call pairing
- prefer fixing message structure and turn compaction before tuning prompts
- finish by stating the exact failure mode, the compatible payload rule, and the smallest safe code change

