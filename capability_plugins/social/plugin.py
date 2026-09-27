from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import hashlib
from pathlib import Path
import re
from typing import Any

from capability_plugins.contracts import PluginManifest
from capability_plugins.loader import load_manifests


_CAPABILITIES = frozenset({"social.capture"})
_ALLOWED_FIELDS = frozenset({"text", "captured_at", "source_ref"})
_PERSON_PATTERN = re.compile(
    r"(?:和|跟)(?P<name>[\u3400-\u4dbf\u4e00-\u9fff]{1,8})"
    r"(?P<activity>吃饭|见面|聊天|通话|散步|喝咖啡|聚会)"
)
_CONTEXT_PATTERN = re.compile(r"(?:他|她|对方)(?:说|提到)?(?P<context>[^；;。,.，]+)")
_COMMITMENT_PATTERN = re.compile(r"我答应(?P<commitment>[^。；;，,]+)")
_DUE_PREFIX = re.compile(
    r"^(?P<due>下周[一二三四五六日天]?|今天|明天|后天|今晚|周末|月底|年底)?"
    r"(?P<action>.+)$"
)


class SocialPluginError(ValueError):
    """Stable, user-safe errors exposed by Social capability calls."""

    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        super().__init__(error_code)


def _load_manifest() -> PluginManifest:
    manifest_dir = Path(__file__).resolve().parents[1] / "manifests"
    for manifest in load_manifests(manifest_dir):
        if manifest.plugin_id == "social":
            return manifest
    raise RuntimeError("social manifest is missing")


class SocialPlugin:
    """Create a low-friction Social capture proposal without persisting it."""

    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self.manifest = _load_manifest()
        self._clock = clock or (lambda: datetime.now().astimezone())

    def invoke(
        self,
        capability: str,
        payload: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        del context
        if capability not in _CAPABILITIES:
            raise SocialPluginError("unsupported_capability")
        if type(payload) is not dict or set(payload) - _ALLOWED_FIELDS:
            raise SocialPluginError("invalid_input")
        return _capture(payload, self._clock)


def _capture(
    payload: dict[str, Any], clock: Callable[[], datetime]
) -> dict[str, Any]:
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        raise SocialPluginError("invalid_input")
    name, activity = _identify_person_and_activity(text)
    captured_at = _parse_timestamp(payload.get("captured_at"), clock)
    source_ref = payload.get("source_ref")
    if source_ref is not None and (
        not isinstance(source_ref, str) or not source_ref.strip() or len(source_ref) > 200
    ):
        raise SocialPluginError("invalid_input")

    occurred_at = captured_at
    if re.search(r"昨天", text):
        occurred_at = captured_at - timedelta(days=1)
    occurred_at_text = _timestamp_text(occurred_at)
    captured_at_text = _timestamp_text(captured_at)
    person_id = _stable_id("person", name)
    interaction_id = _stable_id(
        "interaction", f"{person_id}|{occurred_at_text}|{activity}|{source_ref or ''}"
    )
    commitment = _parse_commitment(text)
    person: dict[str, Any] = {
        "person_id": person_id,
        "name": name,
        "relationship": "unspecified",
        "last_contact_at": occurred_at_text,
    }
    interaction_context = _extract_context(text, name)
    interaction: dict[str, Any] = {
        "interaction_id": interaction_id,
        "person_id": person_id,
        "occurred_at": occurred_at_text,
        "activity": activity,
        "context": interaction_context,
    }
    if source_ref is not None:
        interaction["source_ref"] = source_ref.strip()

    result: dict[str, Any] = {
        "proposal_type": "social_capture",
        "person": person,
        "interaction": interaction,
        "captured_at": captured_at_text,
        "status": "pending_human_review",
        "executed": False,
        "requires_human_review": True,
    }
    if commitment is not None:
        action, due_text = commitment
        external_description = f"向{name}{action}"
        if len(action) > 300 or len(external_description) > 300:
            raise SocialPluginError("invalid_input")
        commitment_id = _stable_id(
            "commitment", f"{person_id}|{captured_at_text}|{action}|{due_text or ''}"
        )
        person["open_commitments"] = [commitment_id]
        person["next_attention"] = due_text
        result["commitment"] = {
            "commitment_id": commitment_id,
            "person_id": person_id,
            "promised_at": captured_at_text,
            "action": action,
            "due_text": due_text,
            "due_at": None,
            "status": "open",
            "external_action": {
                "action_type": "send_material" if "发" in action else "send_message",
                "description": external_description,
                "approval": {"status": "pending_human_review"},
                "requires_human_review": True,
                "executed": False,
            },
        }
    return result


def _identify_person_and_activity(text: str) -> tuple[str, str]:
    match = _PERSON_PATTERN.search(text)
    if match is None:
        raise SocialPluginError("person_not_identified")
    return match.group("name"), match.group("activity")


def _parse_timestamp(value: Any, clock: Callable[[], datetime]) -> datetime:
    if value is None:
        try:
            parsed = clock()
        except Exception:
            raise SocialPluginError("reference_time_unavailable") from None
        if (
            not isinstance(parsed, datetime)
            or parsed.tzinfo is None
            or parsed.utcoffset() is None
        ):
            raise SocialPluginError("reference_time_unavailable")
        return parsed.replace(microsecond=0)
    if not isinstance(value, str):
        raise SocialPluginError("invalid_input")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise SocialPluginError("invalid_input") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SocialPluginError("invalid_input")
    return parsed.replace(microsecond=0)


def _timestamp_text(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat(timespec="seconds")


def _extract_context(text: str, name: str) -> list[str]:
    match = _CONTEXT_PATTERN.search(text)
    if match is None:
        return []
    context = match.group("context").strip()
    if not context:
        return []
    value = f"{name}{context}"
    if len(value) > 500:
        raise SocialPluginError("invalid_input")
    return [value]


def _parse_commitment(text: str) -> tuple[str, str | None] | None:
    match = _COMMITMENT_PATTERN.search(text)
    if match is None:
        return None
    phrase = match.group("commitment").strip()
    parsed = _DUE_PREFIX.fullmatch(phrase)
    if parsed is None:
        raise SocialPluginError("invalid_input")
    action = parsed.group("action").strip()
    due_text = parsed.group("due")
    if not action:
        raise SocialPluginError("invalid_input")
    return action, due_text


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"
