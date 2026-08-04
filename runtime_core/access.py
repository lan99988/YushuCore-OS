from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


VALID_SENSITIVITY = {"level_0", "level_1", "level_2", "level_3", "level_4"}


class AccessRequestDenied(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AccessRequest:
    request_id: str
    agent_id: str
    resource: str
    reason: str
    sensitivity: str
    status: str
    created: str
    reviewer: str | None = None
    review_reason: str | None = None
    review_time: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "AccessRequest":
        return cls(**value)


class AccessRequestStore:
    def __init__(self, state_path: str | Path) -> None:
        self.root = Path(state_path) / "access_requests"
        self.root.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        *,
        agent_id: str,
        resource: str,
        reason: str,
        sensitivity: str,
    ) -> AccessRequest:
        if not resource.strip():
            raise ValueError("access resource is required")
        if not reason.strip():
            raise ValueError("access reason is required")
        if sensitivity not in VALID_SENSITIVITY:
            raise ValueError("invalid access sensitivity")
        request = AccessRequest(
            request_id=uuid4().hex,
            agent_id=agent_id,
            resource=resource,
            reason=reason,
            sensitivity=sensitivity,
            status="pending",
            created=_now(),
        )
        self.save(request)
        return request

    def load(self, request_id: str) -> AccessRequest:
        path = self.root / f"{request_id}.json"
        if not path.exists():
            raise KeyError(f"Unknown access request: {request_id}")
        return AccessRequest.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, request: AccessRequest) -> None:
        path = self.root / f"{request.request_id}.json"
        path.write_text(
            json.dumps(request.to_dict(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def approve(self, request_id: str, *, reviewer: str, reason: str) -> AccessRequest:
        return self._review(request_id, status="approved", reviewer=reviewer, reason=reason)

    def reject(self, request_id: str, *, reviewer: str, reason: str) -> AccessRequest:
        return self._review(request_id, status="rejected", reviewer=reviewer, reason=reason)

    def _review(
        self,
        request_id: str,
        *,
        status: str,
        reviewer: str,
        reason: str,
    ) -> AccessRequest:
        if not reviewer.strip():
            raise ValueError("reviewer is required")
        if not reason.strip():
            raise ValueError("review reason is required")
        request = self.load(request_id)
        if request.status != "pending":
            raise ValueError("access request is not pending")
        reviewed = replace(
            request,
            status=status,
            reviewer=reviewer,
            review_reason=reason,
            review_time=_now(),
        )
        self.save(reviewed)
        return reviewed
