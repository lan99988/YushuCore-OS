from __future__ import annotations

from datetime import date
from pathlib import Path
import re
from typing import Any

from capability_plugins.contracts import PluginManifest
from capability_plugins.loader import load_manifests


_CAPABILITIES = frozenset({"life_admin.domains", "life_admin.capture"})
_DOMAINS = (
    ("identity_documents", "证件与身份"),
    ("home_facilities", "住房与生活设施"),
    ("personal_asset_maintenance", "个人资产维护"),
    ("services_contracts", "服务与合同"),
    ("administrative_procedures", "行政手续"),
)
_MONTH_PATTERNS = (
    re.compile(r"明年\s*(?P<month>1[0-2]|[1-9])\s*月"),
    re.compile(r"今年\s*(?P<month>1[0-2]|[1-9])\s*月"),
    re.compile(r"(?P<year>20\d{2})\s*年\s*(?P<month>1[0-2]|[1-9])\s*月"),
)
_BARE_MONTH = re.compile(r"(?<!年)(?P<month>1[0-2]|[1-9])\s*月")


class LifeAdminPluginError(ValueError):
    """Safe, stable errors exposed by Life Administration capability calls."""

    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(message)


def _load_manifest() -> PluginManifest:
    manifest_dir = Path(__file__).resolve().parents[1] / "manifests"
    for manifest in load_manifests(manifest_dir):
        if manifest.plugin_id == "life_admin":
            return manifest
    raise RuntimeError("life_admin manifest is missing")


class LifeAdminPlugin:
    """Progressively activates only observed Life Administration subdomains."""

    def __init__(self) -> None:
        self.manifest = _load_manifest()
        self._active_subdomains: set[str] = set()

    def invoke(
        self,
        capability: str,
        payload: dict[str, Any],
        context: Any,
    ) -> Any:
        if capability not in _CAPABILITIES:
            raise LifeAdminPluginError(
                "unsupported_capability",
                "The requested Life Administration capability is unsupported.",
            )
        if type(payload) is not dict:
            raise LifeAdminPluginError(
                "invalid_input", "Life Administration payload must be a dictionary."
            )
        if capability == "life_admin.domains":
            return self._domains()
        return self._capture(payload, context)

    def _domains(self) -> dict[str, Any]:
        domains = []
        for domain_id, label in _DOMAINS:
            active = any(
                entry.startswith(f"{domain_id}.")
                for entry in self._active_subdomains
            )
            domains.append(
                {
                    "domain_id": domain_id,
                    "label": label,
                    "activation_state": "active" if active else "dormant",
                }
            )
        return {
            "domains": domains,
            "active_subdomains": sorted(self._active_subdomains),
        }

    def _capture(self, payload: dict[str, Any], context: Any) -> dict[str, Any]:
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            raise LifeAdminPluginError(
                "invalid_input", "Life Administration capture text is required."
            )
        reference_date = payload.get("reference_date")
        parsing_context = (
            {"today": reference_date}
            if isinstance(reference_date, str)
            else context
        )
        parsed = _parse_passport_expiry(text.strip(), parsing_context)
        if parsed is None:
            return {
                "recognized": False,
                "activated_subdomain": None,
                "item": None,
                "proposals": [],
            }

        category, subdomain, title, expires_at, clarification = parsed
        if clarification is not None:
            return {
                "recognized": True,
                "needs_clarification": True,
                "reason_code": clarification,
                "activated_subdomain": None,
                "item": None,
                "proposals": [],
            }
        activated_subdomain = f"{category}.{subdomain}"
        self._active_subdomains.add(activated_subdomain)
        item: dict[str, Any] = {
            "item_id": f"{subdomain}:{expires_at or 'active'}",
            "title": title,
            "category": category,
            "subdomain": subdomain,
            "status": "active",
            "persisted": False,
        }
        proposals = []
        if expires_at is not None:
            item["expires_at"] = expires_at
            year, month = (int(part) for part in expires_at.split("-"))
            proposals.append(
                {
                    "proposal_type": "reminder",
                    "title": f"护照将于{year}年{month}月到期",
                    "due_at": expires_at,
                    "status": "pending_human_review",
                    "executed": False,
                    "requires_human_review": True,
                }
            )
        return {
            "recognized": True,
            "activated_subdomain": activated_subdomain,
            "item": item,
            "proposals": proposals,
        }


def _parse_passport_expiry(
    text: str, context: Any
) -> tuple[str, str, str, str | None, str | None] | None:
    if "护照" not in text or not any(
        word in text for word in ("到期", "过期", "有效期", "续期", "换发")
    ):
        return None
    expires_at, error = _extract_month(text, context)
    return "identity_documents", "passport", "护照", expires_at, error


def _extract_month(text: str, context: Any) -> tuple[str | None, str | None]:
    today = _context_date(context)
    if today is None:
        return None, "reference_date_required"
    for index, pattern in enumerate(_MONTH_PATTERNS):
        match = pattern.search(text)
        if match is None:
            continue
        month = int(match.group("month"))
        if index == 0:
            year = today.year + 1
        elif index == 1:
            year = today.year
        else:
            year = int(match.group("year"))
        expires_at = f"{year:04d}-{month:02d}"
        if (year, month) < (today.year, today.month):
            return None, "expiry_date_in_past"
        return expires_at, None
    if _BARE_MONTH.search(text):
        return None, "expiry_year_required"
    return None, "expiry_date_required"


def _context_date(context: Any) -> date | None:
    if isinstance(context, dict):
        value = context.get("today")
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except ValueError:
                pass
    return None
