from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from evo_harness.models import AnalysisReport, EvolutionProposal, TaskTrace, WorkspaceSnapshot


class BaseOperator(ABC):
    @abstractmethod
    def build_change_request(
        self,
        trace: TaskTrace,
        workspace: WorkspaceSnapshot,
        report: AnalysisReport,
        proposal: EvolutionProposal,
    ) -> dict[str, Any]:
        raise NotImplementedError

