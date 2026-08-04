import os
import sys
import unittest


WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(WORKSPACE, "08_工具脚本（Tools）", "身体管理")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)


class GarminIncrementalSyncTest(unittest.TestCase):
    def test_merge_daily_items_replaces_window_and_keeps_history(self):
        from garmin_incremental_sync import merge_daily_items

        old_items = [
            {"calendarDate": "2026-07-10", "totalSteps": 1000},
            {"calendarDate": "2026-07-20", "totalSteps": 2000},
            {"error": "HTTPError", "path": "/x/2026-07-21"},
        ]
        new_items = [
            {"calendarDate": "2026-07-20", "totalSteps": 2500},
            {"calendarDate": "2026-07-21", "totalSteps": 3000},
        ]
        merged = merge_daily_items(
            old_items, new_items, {"2026-07-20", "2026-07-21"}
        )

        dates = [item.get("calendarDate") or item.get("path") for item in merged]
        self.assertEqual(
            [item.get("calendarDate") for item in merged],
            ["2026-07-10", "2026-07-20", "2026-07-21"],
        )
        by_date = {item.get("calendarDate"): item for item in merged}
        self.assertEqual(by_date["2026-07-20"]["totalSteps"], 2500)
        self.assertNotIn("/x/2026-07-21", dates)

    def test_merge_daily_items_drops_undated_stale_entries(self):
        from garmin_incremental_sync import merge_daily_items

        old_items = [{"error": "Timeout", "message": "boom"}]
        merged = merge_daily_items(old_items, [], {"2026-07-20"})
        self.assertEqual(merged, [])

    def test_merge_activities_dedupes_by_activity_id(self):
        from garmin_incremental_sync import merge_activities

        old_items = [
            {"activityId": 1, "startTimeLocal": "2026-07-01 07:00:00", "note": "old"},
            {"activityId": 2, "startTimeLocal": "2026-07-15 07:00:00"},
        ]
        new_items = [
            {"activityId": 2, "startTimeLocal": "2026-07-15 07:00:00", "note": "new"},
            {"activityId": 3, "startTimeLocal": "2026-07-28 07:00:00"},
        ]
        merged = merge_activities(old_items, new_items)

        self.assertEqual([item["activityId"] for item in merged], [1, 2, 3])
        self.assertEqual(merged[1]["note"], "new")

    def test_merge_raw_sets_schema_version_and_window_meta(self):
        from garmin_incremental_sync import SCHEMA_VERSION, merge_raw

        old_raw = {
            "meta": {"start": "2025-07-30", "end": "2026-07-15"},
            "activities": [],
            "daily_summary": [
                {"calendarDate": "2026-07-10", "totalSteps": 1000}
            ],
        }
        new_raw = {
            "activities": [],
            "daily_summary": [
                {"calendarDate": "2026-07-20", "totalSteps": 2000}
            ],
        }
        merged = merge_raw(
            old_raw,
            new_raw,
            window_start="2026-07-16",
            window_end="2026-07-29",
            sync_time="2026-07-29T08:00:00",
        )

        meta = merged["meta"]
        self.assertEqual(meta["schema_version"], SCHEMA_VERSION)
        self.assertEqual(meta["sync_time"], "2026-07-29T08:00:00")
        self.assertEqual(meta["source"], "garmin")
        self.assertEqual(meta["start"], "2025-07-30")
        self.assertEqual(meta["end"], "2026-07-29")
        self.assertEqual(
            meta["last_incremental_window"],
            {"start": "2026-07-16", "end": "2026-07-29"},
        )
        self.assertEqual(
            [item["calendarDate"] for item in merged["daily_summary"]],
            ["2026-07-10", "2026-07-20"],
        )

    def test_merge_raw_keeps_all_daily_dimension_keys(self):
        from garmin_incremental_sync import DAILY_KEYS, merge_raw

        old_raw = {key: [] for key in DAILY_KEYS}
        old_raw["meta"] = {"start": "2026-07-01", "end": "2026-07-15"}
        old_raw["activities"] = []
        merged = merge_raw(
            old_raw,
            {},
            window_start="2026-07-16",
            window_end="2026-07-29",
        )
        for key in DAILY_KEYS:
            self.assertIn(key, merged)


if __name__ == "__main__":
    unittest.main()
