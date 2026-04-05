from __future__ import annotations

from typing import Any

from evo_harness.adapters.base import HarnessAdapter
from evo_harness.models import HarnessCapabilities


class OpenHarnessAdapter(HarnessAdapter):
    """Capability adapter for OpenHarness-like manifests."""

    name = "openharness"

    def capabilities_from_manifest(self, payload: dict[str, Any]) -> HarnessCapabilities:
        features = payload.get("features", payload)
        normalized = {
            "adapter_name": payload.get("adapter_name", self.name),
            "features": {
                "skill_upgrade": features.get("skill_upgrade", features.get("skills", False)),
                "skill_validate": features.get("skill_validate", True),
                "skill_rollback": features.get("skill_rollback", True),
                "memory_write": features.get("memory_write", features.get("memory", False)),
                "memory_archive": features.get("memory_archive", features.get("memory", False)),
                "session_fork": features.get("session_fork", features.get("sessions", False)),
                "agent_clone": features.get("agent_clone", features.get("agents", False)),
                "replay_validation": features.get("replay_validation", True),
                "regression_suite": features.get("regression_suite", True),
                "artifact_access": features.get("artifact_access", features.get("execution", False)),
                "execution_history": features.get("execution_history", features.get("sessions", False)),
                "hooks": features.get("hooks", False),
                "subagents": features.get("subagents", features.get("planning", False)),
                "slash_commands": features.get("slash_commands", True),
                "permission_rules": features.get("permission_rules", True),
                "workspace_instructions": features.get("workspace_instructions", True),
            },
        }
        return HarnessCapabilities.from_dict(normalized)

