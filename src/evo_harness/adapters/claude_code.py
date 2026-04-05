from __future__ import annotations

from typing import Any

from evo_harness.adapters.base import HarnessAdapter
from evo_harness.models import HarnessCapabilities


class ClaudeCodeAdapter(HarnessAdapter):
    """Capability adapter for Claude Code style workspace/settings manifests."""

    name = "claude-code"

    def capabilities_from_manifest(self, payload: dict[str, Any]) -> HarnessCapabilities:
        permissions = payload.get("permissions", {})
        sandbox = payload.get("sandbox", {})
        features = payload.get("features", {})
        hooks = payload.get("hooks", {})

        normalized = {
            "adapter_name": payload.get("adapter_name", self.name),
            "features": {
                "skill_upgrade": bool(features.get("skills", True)),
                "skill_validate": bool(features.get("commands", True)),
                "skill_rollback": bool(features.get("git_backed_workspace", True)),
                "memory_write": bool(features.get("memory", True)),
                "memory_archive": bool(features.get("memory", True)),
                "session_fork": bool(features.get("sessions", True)),
                "agent_clone": bool(features.get("agents", True)),
                "replay_validation": bool(features.get("commands", True)),
                "regression_suite": bool(features.get("commands", True)),
                "artifact_access": bool(features.get("workspace_access", True)),
                "execution_history": bool(features.get("sessions", True)),
                "hooks": bool(hooks) or bool(features.get("hooks", True)),
                "subagents": bool(features.get("subagents", True)),
                "slash_commands": bool(features.get("slash_commands", True)),
                "permission_rules": bool(permissions) or bool(sandbox),
                "workspace_instructions": bool(features.get("workspace_instructions", True)),
            },
        }
        return HarnessCapabilities.from_dict(normalized)
