from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from hashlib import sha1
from pathlib import Path
from typing import Any

from evo_harness.harness.settings import ApprovalSettings


@dataclass(slots=True)
class ApprovalRequest:
    id: str
    fingerprint: str
    tool_name: str
    arguments: dict[str, Any]
    reason: str
    command: str | None = None
    file_path: str | None = None
    status: str = "pending"
    created_at: float = field(default_factory=time.time)
    decided_at: float | None = None
    decision_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ApprovalRequest":
        return cls(
            id=str(payload["id"]),
            fingerprint=str(payload["fingerprint"]),
            tool_name=str(payload["tool_name"]),
            arguments=dict(payload.get("arguments", {})),
            reason=str(payload.get("reason", "")),
            command=payload.get("command"),
            file_path=payload.get("file_path"),
            status=str(payload.get("status", "pending")),
            created_at=float(payload.get("created_at", time.time())),
            decided_at=payload.get("decided_at"),
            decision_note=str(payload.get("decision_note", "")),
        )


class ApprovalManager:
    def __init__(self, workspace: str | Path, settings: ApprovalSettings) -> None:
        self.workspace = Path(workspace).resolve()
        self.settings = settings
        self.root = self.workspace / ".evo-harness" / "approvals"
        self.requests_dir = self.root / "requests"
        self.decisions_dir = self.root / "decisions"
        self.requests_dir.mkdir(parents=True, exist_ok=True)
        self.decisions_dir.mkdir(parents=True, exist_ok=True)

    def fingerprint(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        command: str | None = None,
        file_path: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {}
        for field_name in self.settings.fingerprint_fields:
            if field_name == "tool_name":
                payload[field_name] = tool_name
            elif field_name == "arguments":
                payload[field_name] = arguments
            elif field_name == "command":
                payload[field_name] = command
            elif field_name == "file_path":
                payload[field_name] = file_path
        return sha1(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()

    def get_cached_decision(self, fingerprint: str) -> ApprovalRequest | None:
        path = self.decisions_dir / f"{fingerprint}.json"
        if not path.exists():
            return None
        return ApprovalRequest.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def submit_request(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        reason: str,
        command: str | None = None,
        file_path: str | None = None,
    ) -> ApprovalRequest:
        fingerprint = self.fingerprint(
            tool_name=tool_name,
            arguments=arguments,
            command=command,
            file_path=file_path,
        )
        existing = self._find_pending_by_fingerprint(fingerprint)
        if existing is not None:
            return existing
        request_id = f"apr-{sha1(f'{fingerprint}:{time.time()}'.encode('utf-8')).hexdigest()[:10]}"
        request = ApprovalRequest(
            id=request_id,
            fingerprint=fingerprint,
            tool_name=tool_name,
            arguments=dict(arguments),
            reason=reason,
            command=command,
            file_path=file_path,
        )
        (self.requests_dir / f"{request_id}.json").write_text(
            json.dumps(request.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return request

    def list_requests(self, *, status: str | None = None) -> list[ApprovalRequest]:
        requests: list[ApprovalRequest] = []
        for path in sorted(self.requests_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            request = ApprovalRequest.from_dict(json.loads(path.read_text(encoding="utf-8")))
            if status is None or request.status == status:
                requests.append(request)
        return requests

    def decide(self, request_id: str, *, approved: bool, note: str = "") -> ApprovalRequest:
        path = self.requests_dir / f"{request_id}.json"
        if not path.exists():
            raise ValueError(f"Approval request not found: {request_id}")
        request = ApprovalRequest.from_dict(json.loads(path.read_text(encoding="utf-8")))
        request.status = "approved" if approved else "denied"
        request.decided_at = time.time()
        request.decision_note = note
        path.write_text(json.dumps(request.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        should_cache = (approved and self.settings.cache_approved_actions) or (
            not approved and self.settings.cache_denied_actions
        )
        if should_cache:
            (self.decisions_dir / f"{request.fingerprint}.json").write_text(
                json.dumps(request.to_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        return request

    def _find_pending_by_fingerprint(self, fingerprint: str) -> ApprovalRequest | None:
        for request in self.list_requests(status="pending"):
            if request.fingerprint == fingerprint:
                return request
        return None
