import datetime as dt
import os
import sys
import unittest


WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(WORKSPACE, "08_工具脚本（Tools）", "身体管理")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)


class GarminSync365dTest(unittest.TestCase):
    def test_date_window_includes_requested_number_of_days(self):
        from garmin_sync_365d import date_window

        start, end, days = date_window(3, today=dt.date(2026, 7, 29))

        self.assertEqual(start.isoformat(), "2026-07-27")
        self.assertEqual(end.isoformat(), "2026-07-29")
        self.assertEqual(days, ["2026-07-27", "2026-07-28", "2026-07-29"])

    def test_fetch_range_calls_stable_daily_dimensions(self):
        from garmin_sync_365d import fetch_range

        class FakeClient:
            def __init__(self):
                self.calls = []

            def display_name(self):
                return "profile123"

            def gc_api(self, path, params=None):
                self.calls.append((path, params or {}))
                if path == "/activitylist-service/activities/search/activities":
                    return []
                return {"path": path, "params": params or {}}

        client = FakeClient()
        raw = fetch_range(client, days=2, today=dt.date(2026, 7, 29))

        self.assertEqual(raw["meta"]["start"], "2026-07-28")
        self.assertEqual(raw["meta"]["end"], "2026-07-29")
        self.assertEqual(len(raw["daily_summary"]), 2)
        self.assertEqual(len(raw["sleep"]), 2)
        self.assertEqual(len(raw["heart_rate"]), 2)
        self.assertEqual(len(raw["stress"]), 2)
        self.assertEqual(len(raw["respiration"]), 2)
        self.assertEqual(len(raw["spo2"]), 2)
        self.assertEqual(len(raw["hrv"]), 2)
        self.assertEqual(len(raw["training_readiness"]), 2)
        self.assertEqual(len(raw["training_status"]), 2)
        self.assertIn(
            (
                "/wellness-service/wellness/bodyBattery/reports/daily",
                {"startDate": "2026-07-28", "endDate": "2026-07-29"},
            ),
            client.calls,
        )

    def test_fetch_activities_filters_to_requested_window(self):
        from garmin_sync_365d import fetch_activities

        class FakeClient:
            def __init__(self):
                self.offsets = []

            def gc_api(self, path, params=None):
                self.offsets.append(int(params["start"]))
                if params["start"] == "0":
                    return [
                        {"activityId": 1, "startTimeLocal": "2026-07-29 08:00:00"},
                        {"activityId": 2, "startTimeLocal": "2025-01-01 08:00:00"},
                    ]
                return []

        activities = fetch_activities(
            FakeClient(),
            start=dt.date(2026, 7, 23),
            end=dt.date(2026, 7, 29),
            page_size=2,
        )

        self.assertEqual([item["activityId"] for item in activities], [1])

    def test_fetch_body_battery_uses_short_windows(self):
        from garmin_sync_365d import fetch_body_battery

        class FakeClient:
            def __init__(self):
                self.calls = []

            def gc_api(self, path, params=None):
                self.calls.append((path, params or {}))
                return [
                    {
                        "date": params["startDate"],
                        "path": path,
                    }
                ]

        items = fetch_body_battery(
            FakeClient(),
            start=dt.date(2026, 7, 1),
            end=dt.date(2026, 7, 29),
            chunk_days=14,
        )

        self.assertEqual(
            [item["date"] for item in items],
            ["2026-07-01", "2026-07-15", "2026-07-29"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
