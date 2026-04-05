from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from evo_harness.models import EvolutionPlan


@dataclass
class EvolutionLedger:
    path: Path

    def append(self, plan: EvolutionPlan, *, status: str = "planned") -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "plan": plan.to_dict(),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True) + "\n")

