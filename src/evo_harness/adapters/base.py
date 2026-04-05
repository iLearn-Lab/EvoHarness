from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from evo_harness.models import HarnessCapabilities


class HarnessAdapter(ABC):
    """Convert harness-specific manifests into a shared capability model."""

    name: str

    @abstractmethod
    def capabilities_from_manifest(self, payload: dict[str, Any]) -> HarnessCapabilities:
        raise NotImplementedError

