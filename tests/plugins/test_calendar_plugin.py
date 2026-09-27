from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
PLUGIN_DIR = ROOT / "capability_plugins" / "calendar"
MANIFEST_PATH = ROOT / "capability_plugins" / "manifests" / "calendar.yaml"
LEGACY_HANDLER_PATH = (
    ROOT
    / "02_执行引擎（Engine）"
    / "输入解析引擎"
    / "handlers"
    / "schedule_calendar.py"
)

EXPECTED_CAPABILITIES = {
    "calendar.list_events",
    "calendar.find_free_slots",
    "calendar.check_conflict",
    "calendar.create_proposal",
    "calendar.move_proposal",
}


def _plugin_api():
    assert (PLUGIN_DIR / "__init__.py").is_file(), "calendar plugin package is missing"
    from capability_plugins.calendar import CalendarPlugin

    return CalendarPlugin


def _manifest_data():
    return yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))


class LegacyCalendarDelegate:
    def __init__(self):
        self.calls = []
        self.events = [
            {
                "summary": "Weekly review",
                "start": "2026-09-28T09:00:00+08:00",
                "end": "2026-09-28T10:00:00+08:00",
            }
        ]
        self.slot = {
            "start": "2026-09-28T11:00:00+08:00",
            "end": "2026-09-28T11:30:00+08:00",
        }
        self.conflicts = [
            {
                "summary": "Weekly review",
                "start": "2026-09-28T09:00:00+08:00",
                "end": "2026-09-28T10:00:00+08:00",
            }
        ]

    def check_date_freebusy(self, target_date=None):
        self.calls.append(("check_date_freebusy", target_date))
        return list(self.events)

    def find_next_available_slot(self, duration_minutes, after_iso):
        self.calls.append(("find_next_available_slot", duration_minutes, after_iso))
        return dict(self.slot)

    def check_slot_freebusy(self, slot_start_iso, slot_end_iso):
        self.calls.append(("check_slot_freebusy", slot_start_iso, slot_end_iso))
        return list(self.conflicts), not self.conflicts

    def create_calendar_event(self, *args, **kwargs):
        raise AssertionError("calendar plugin must never create an external event")

    def reschedule_conflict(self, *args, **kwargs):
        raise AssertionError("calendar plugin must never move an external event")


def test_calendar_manifest_declares_capabilities_and_permissions():
    manifest = _manifest_data()

    assert set(manifest["provides"]) == EXPECTED_CAPABILITIES
    assert {"read_calendar", "propose_calendar_change"} <= set(manifest["permissions"])
    assert "feishu.calendar" in manifest["reads"]
    assert manifest["writes"] == []


def test_calendar_manifest_permissions_are_checked_by_action_policy():
    from capability_plugins.manifest import manifest_from_dict
    from runtime_core.action_policy import ActionPolicy
    from runtime_core.models import ActionAuthority, PlannedAction

    manifest = manifest_from_dict(_manifest_data())
    action = PlannedAction(
        action_id="proposal-1",
        plugin_id="calendar",
        capability="calendar.create_proposal",
        authority=ActionAuthority.AUTONOMOUS,
        reversible=True,
        external_effect=False,
        affects_commitment=False,
        risk="medium",
        payload_digest="a" * 64,
        operation="calendar.create_proposal",
        resource="plugin:calendar",
        required_permissions=("propose_calendar_change",),
    )

    decision = ActionPolicy().evaluate(
        action,
        plugin_permissions=manifest.permissions,
        agent_permissions=("read_calendar",),
        agent_autonomy_level=2,
        known_capabilities=manifest.provides,
    )

    assert decision.allowed is False
    assert decision.reason_code == "agent_permission_denied"


def test_list_events_maps_to_legacy_read_and_preserves_event_fields():
    CalendarPlugin = _plugin_api()
    delegate = LegacyCalendarDelegate()
    plugin = CalendarPlugin(delegate)

    result = plugin.invoke(
        "calendar.list_events",
        {"target_date": "2026-09-28"},
        {"agent_id": "test-agent", "network_mode": "ASSIST"},
    )

    assert result == {"ok": True, "type": "calendar", "events": delegate.events}
    assert delegate.calls == [("check_date_freebusy", "2026-09-28")]


def test_find_free_slots_wraps_legacy_next_available_slot():
    CalendarPlugin = _plugin_api()
    delegate = LegacyCalendarDelegate()
    plugin = CalendarPlugin(delegate)

    result = plugin.invoke(
        "calendar.find_free_slots",
        {"duration_minutes": 30, "after_iso": "2026-09-28T10:30:00+08:00"},
        {"network_mode": "ASSIST"},
    )

    assert result == {"ok": True, "type": "calendar", "slots": [delegate.slot]}
    assert delegate.calls == [
        ("find_next_available_slot", 30, "2026-09-28T10:30:00+08:00")
    ]


def test_check_conflict_maps_legacy_busy_tuple():
    CalendarPlugin = _plugin_api()
    delegate = LegacyCalendarDelegate()
    plugin = CalendarPlugin(delegate)

    result = plugin.invoke(
        "calendar.check_conflict",
        {
            "start_iso": "2026-09-28T09:00:00+08:00",
            "end_iso": "2026-09-28T10:00:00+08:00",
        },
        {"network_mode": "ASSIST"},
    )

    assert result == {
        "ok": True,
        "type": "calendar",
        "conflicts": delegate.conflicts,
        "is_free": False,
    }
    assert delegate.calls == [
        (
            "check_slot_freebusy",
            "2026-09-28T09:00:00+08:00",
            "2026-09-28T10:00:00+08:00",
        )
    ]


@pytest.mark.parametrize(
    ("capability", "payload", "expected_method"),
    [
        (
            "calendar.list_events",
            {"target_date": "2026-09-28"},
            "check_date_freebusy",
        ),
        (
            "calendar.find_free_slots",
            {"duration_minutes": 25, "after_iso": "2026-09-28T12:00:00+08:00"},
            "find_next_available_slot",
        ),
        (
            "calendar.check_conflict",
            {
                "start_iso": "2026-09-28T09:00:00+08:00",
                "end_iso": "2026-09-28T10:00:00+08:00",
            },
            "check_slot_freebusy",
        ),
    ],
)
def test_legacy_delegate_failures_are_mapped_without_leaking_exception_text(
    capability, payload, expected_method
):
    CalendarPlugin = _plugin_api()
    from capability_plugins.calendar import CalendarPluginError

    class BrokenDelegate(LegacyCalendarDelegate):
        def __getattribute__(self, name):
            if name == expected_method:
                raise RuntimeError("private calendar token must not escape")
            return super().__getattribute__(name)

    with pytest.raises(CalendarPluginError) as exc_info:
        CalendarPlugin(BrokenDelegate()).invoke(
            capability, payload, {"network_mode": "ASSIST"}
        )

    assert exc_info.value.error_code == "calendar_sync_failed"
    assert "private calendar token" not in str(exc_info.value)


def test_missing_delegate_fails_closed_without_importing_legacy_calendar_module():
    CalendarPlugin = _plugin_api()
    from capability_plugins.calendar import CalendarPluginError
    not_imported = object()
    old_module = sys.modules.get("calendar_sync", not_imported)

    with pytest.raises(CalendarPluginError) as exc_info:
        CalendarPlugin().invoke(
            "calendar.list_events",
            {"target_date": "2026-09-28"},
            {"network_mode": "ASSIST"},
        )

    assert exc_info.value.error_code == "calendar_module_unavailable"
    assert sys.modules.get("calendar_sync", not_imported) is old_module


def test_legacy_missing_module_error_maps_to_stable_unavailable_code():
    CalendarPlugin = _plugin_api()
    from capability_plugins.calendar import CalendarPluginError

    class MissingModuleDelegate(LegacyCalendarDelegate):
        def check_date_freebusy(self, target_date=None):
            raise ImportError("legacy calendar module unavailable")

    with pytest.raises(CalendarPluginError) as exc_info:
        CalendarPlugin(MissingModuleDelegate()).invoke(
            "calendar.list_events",
            {"target_date": "2026-09-28"},
            {"network_mode": "ASSIST"},
        )

    assert exc_info.value.error_code == "calendar_module_unavailable"
    assert "legacy calendar module unavailable" not in str(exc_info.value)


def test_create_and_move_return_proposals_without_calling_external_writers():
    CalendarPlugin = _plugin_api()
    delegate = LegacyCalendarDelegate()
    plugin = CalendarPlugin(delegate)

    create_result = plugin.invoke(
        "calendar.create_proposal",
        {
            "summary": "Project review",
            "start_iso": "2026-09-28T14:00:00+08:00",
            "end_iso": "2026-09-28T15:00:00+08:00",
        },
        {},
    )
    move_result = plugin.invoke(
        "calendar.move_proposal",
        {
            "event_id": "event-7",
            "new_start_iso": "2026-09-28T15:00:00+08:00",
            "new_end_iso": "2026-09-28T16:00:00+08:00",
        },
        {},
    )

    for result in (create_result, move_result):
        assert result["ok"] is True
        assert result["status"] == "pending_human_review"
        assert result["executed"] is False
        assert result["affects_commitment"] is False
    assert delegate.calls == []


@pytest.mark.parametrize(
    ("capability", "payload"),
    [
        (
            "calendar.create_proposal",
            {
                "summary": "Commitment",
                "start_iso": "2026-09-28T14:00:00+08:00",
                "end_iso": "2026-09-28T15:00:00+08:00",
                "fixed_meeting": True,
            },
        ),
        (
            "calendar.create_proposal",
            {
                "summary": "Commitment",
                "start_iso": "2026-09-28T14:00:00+08:00",
                "end_iso": "2026-09-28T15:00:00+08:00",
                "external_commitment": True,
            },
        ),
        (
            "calendar.move_proposal",
            {
                "event_id": "event-7",
                "new_start_iso": "2026-09-28T14:00:00+08:00",
                "new_end_iso": "2026-09-28T15:00:00+08:00",
                "fixed_meeting": True,
            },
        ),
        (
            "calendar.move_proposal",
            {
                "event_id": "event-7",
                "new_start_iso": "2026-09-28T14:00:00+08:00",
                "new_end_iso": "2026-09-28T15:00:00+08:00",
                "external_commitment": True,
            },
        ),
    ],
)
def test_fixed_meeting_and_external_commitment_proposals_are_marked(
    capability, payload
):
    CalendarPlugin = _plugin_api()
    plugin = CalendarPlugin()

    result = plugin.invoke(capability, payload, {})

    assert result["affects_commitment"] is True
    assert result["proposal"]["affects_commitment"] is True
    assert result["executed"] is False


def test_unknown_capability_is_rejected():
    CalendarPlugin = _plugin_api()
    from capability_plugins.calendar import CalendarPluginError

    with pytest.raises(CalendarPluginError) as exc_info:
        CalendarPlugin().invoke("calendar.delete_event", {}, {})
    assert exc_info.value.error_code == "unsupported_capability"


def test_legacy_entrypoint_remains_independent_when_plugin_has_no_delegate(monkeypatch):
    CalendarPlugin = _plugin_api()
    from capability_plugins.calendar import CalendarPluginError

    with pytest.raises(CalendarPluginError):
        CalendarPlugin().invoke(
            "calendar.list_events", {}, {"network_mode": "ASSIST"}
        )

    daily_scheduler = ModuleType("daily_scheduler")
    daily_scheduler.get_today_tasks = lambda target_date: [{"task": "review"}]
    daily_scheduler.get_subject_baselines = lambda: {}
    daily_scheduler.generate_schedule = lambda tasks, baselines, target_date, dry_run: {
        "timeline": [{"slot": "review", "time": "09:00-10:00"}]
    }
    calendar_sync = ModuleType("calendar_sync")
    calendar_sync.sync_schedule_to_calendar = lambda schedule, target_date, dry_run=False: {
        "ok": True,
        "created": 0,
        "conflicts": [],
    }
    monkeypatch.setitem(sys.modules, "daily_scheduler", daily_scheduler)
    monkeypatch.setitem(sys.modules, "calendar_sync", calendar_sync)

    spec = importlib.util.spec_from_file_location(
        "legacy_schedule_calendar_test", LEGACY_HANDLER_PATH
    )
    assert spec is not None and spec.loader is not None
    legacy_handler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy_handler)

    result = legacy_handler.handle_schedule_calendar("#排程到日历", dry_run=True)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert "[TEST]" in result["message"]


def test_runtime_network_off_blocks_calendar_delegate_before_any_external_read():
    CalendarPlugin = _plugin_api()
    from capability_plugins.calendar import CalendarPluginError

    delegate = LegacyCalendarDelegate()
    with pytest.raises(CalendarPluginError) as exc_info:
        CalendarPlugin(delegate).invoke(
            "calendar.list_events",
            {"target_date": "2026-09-28"},
            {"network_mode": "OFF"},
        )

    assert exc_info.value.error_code == "network_access_disabled"
    assert delegate.calls == []


def test_missing_network_mode_fails_closed_before_any_external_read():
    CalendarPlugin = _plugin_api()
    from capability_plugins.calendar import CalendarPluginError

    delegate = LegacyCalendarDelegate()
    with pytest.raises(CalendarPluginError) as exc_info:
        CalendarPlugin(delegate).invoke(
            "calendar.list_events",
            {"target_date": "2026-09-28"},
            {},
        )

    assert exc_info.value.error_code == "network_access_disabled"
    assert delegate.calls == []


def test_explicit_legacy_module_bridge_maps_the_real_calendar_api_shape():
    CalendarPlugin = _plugin_api()
    module = ModuleType("calendar_sync_bridge_test")
    delegate = LegacyCalendarDelegate()

    def check_date_freebusy(target_date=None, *, strict=False):
        assert strict is True
        return delegate.check_date_freebusy(target_date)

    def find_next_available_slot(duration_minutes, after_iso, *, strict=False):
        assert strict is True
        return delegate.find_next_available_slot(duration_minutes, after_iso)

    def check_slot_freebusy(slot_start_iso, slot_end_iso, *, strict=False):
        assert strict is True
        return delegate.check_slot_freebusy(slot_start_iso, slot_end_iso)

    module.check_date_freebusy = check_date_freebusy
    module.find_next_available_slot = find_next_available_slot
    module.check_slot_freebusy = check_slot_freebusy

    plugin = CalendarPlugin.from_legacy_module(module)
    result = plugin.invoke(
        "calendar.list_events",
        {"target_date": "2026-09-28"},
        {"network_mode": "ASSIST"},
    )

    assert result["events"] == delegate.events
    assert delegate.calls == [("check_date_freebusy", "2026-09-28")]


@pytest.mark.parametrize(
    ("capability", "payload"),
    [
        ("calendar.list_events", {"target_date": "2026-09-28"}),
        (
            "calendar.find_free_slots",
            {"duration_minutes": 30, "after_iso": "2026-09-28T10:30:00+08:00"},
        ),
        (
            "calendar.check_conflict",
            {
                "start_iso": "2026-09-28T09:00:00+08:00",
                "end_iso": "2026-09-28T10:00:00+08:00",
            },
        ),
    ],
)
def test_real_legacy_bridge_never_converts_backend_failure_to_empty_success(
    capability, payload
):
    CalendarPlugin = _plugin_api()
    from capability_plugins.calendar import CalendarPluginError

    spec = importlib.util.spec_from_file_location(
        "legacy_calendar_sync_strict_test",
        ROOT / "02_执行引擎（Engine）" / "每日排程引擎" / "calendar_sync.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._lark_json = lambda args: {"ok": False, "error": "private backend detail"}
    plugin = CalendarPlugin.from_legacy_module(module)

    with pytest.raises(CalendarPluginError) as exc_info:
        plugin.invoke(capability, payload, {"network_mode": "ASSIST"})

    assert exc_info.value.error_code == "calendar_sync_failed"
    assert "private backend detail" not in str(exc_info.value)
