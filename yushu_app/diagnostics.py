"""Read-only connector probes with stable, non-secret status codes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping


class ConnectorDiagnostics:
    def __init__(self, probes: Mapping[str, Callable[[], Any] | None], *, max_age_hours: int = 24) -> None:
        self.probes = dict(probes)
        self.max_age = timedelta(hours=max_age_hours)

    def run(self, *, live: bool = False) -> dict[str, dict[str, Any]]:
        report: dict[str, dict[str, Any]] = {}
        for name, probe in self.probes.items():
            if probe is None:
                report[name] = {"status": "not_configured", "stale": True}
                continue
            if not live:
                report[name] = {"status": "configured_unverified", "stale": True}
                continue
            try:
                result = probe()
            except TimeoutError:
                report[name] = {"status": "timeout", "stale": True}
                continue
            except Exception as exc:
                message = str(exc).lower()
                status = "auth_required" if "401" in message or "403" in message or "unauthorized" in message else "provider_unavailable"
                report[name] = {"status": status, "stale": True}
                continue
            if not isinstance(result, dict):
                report[name] = {"status": "provider_unavailable", "stale": True}
                continue
            status = result.get("status", "online")
            if status == "available":
                status = "online"
            if status not in {"online", "auth_required", "provider_unavailable", "timeout", "offline_cache"}:
                status = "provider_unavailable"
            observed_at = result.get("observed_at")
            stale = status != "online"
            if isinstance(observed_at, str):
                try:
                    moment = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
                    stale = stale or moment.tzinfo is None or datetime.now(timezone.utc) - moment > self.max_age
                except ValueError:
                    stale = True
            report[name] = {"status": status, "stale": stale,
                            "observed_at": observed_at if isinstance(observed_at, str) else None}
        return report
