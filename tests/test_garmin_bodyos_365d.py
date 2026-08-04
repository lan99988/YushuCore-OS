import os
import sys
import unittest


WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(WORKSPACE, "08_工具脚本（Tools）", "身体管理")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)


class GarminBodyOS365dTest(unittest.TestCase):
    def test_derive_daily_mental_state_prioritizes_low_body_battery(self):
        from garmin_bodyos_365d import derive_daily_mental_state

        result = derive_daily_mental_state(
            {
                "date": "2026-07-28",
                "body_battery": 18,
                "readiness_score": 61,
                "sleep_hours": 6.68,
                "stress_level": 36,
            }
        )

        self.assertEqual(result["mental_state"], "depleted")
        self.assertEqual(result["study_load"], "recovery")
        self.assertEqual(result["status"], "差")
        self.assertLess(result["energy_coefficient"], 0.8)
        self.assertIn("身体可用能量18", result["reason"])

    def test_derive_daily_mental_state_maps_study_load_tiers(self):
        from garmin_bodyos_365d import derive_daily_mental_state

        deep = derive_daily_mental_state(
            {
                "body_battery": 75,
                "readiness_score": 70,
                "sleep_hours": 7.4,
                "stress_level": 32,
            }
        )
        standard = derive_daily_mental_state(
            {
                "body_battery": 48,
                "readiness_score": 55,
                "sleep_hours": 6.6,
                "stress_level": 42,
            }
        )
        light = derive_daily_mental_state(
            {
                "body_battery": 32,
                "readiness_score": 58,
                "sleep_hours": 6.4,
                "stress_level": 40,
            }
        )

        self.assertEqual(deep["study_load"], "deep")
        self.assertEqual(deep["status"], "好")
        self.assertEqual(standard["study_load"], "standard")
        self.assertEqual(standard["status"], "一般")
        self.assertEqual(light["study_load"], "light")
        self.assertEqual(light["status"], "差")

    def test_build_today_energy_context_uses_latest_valid_energy_day(self):
        from garmin_bodyos_365d import build_today_energy_context

        dataset = {
            "source": "garmin",
            "calibration": {"excluded_no_data_days": 4},
            "energy_daily": [
                {
                    "date": "2026-07-27",
                    "body_battery": 55,
                    "readiness_score": 56,
                    "sleep_hours": 6.28,
                    "stress_level": 43,
                },
                {
                    "date": "2026-07-28",
                    "body_battery": 18,
                    "readiness_score": 61,
                    "sleep_hours": 6.68,
                    "stress_level": 36,
                },
            ],
        }

        context = build_today_energy_context(dataset, today="2026-07-29")

        self.assertEqual(context["date"], "2026-07-28")
        self.assertEqual(context["requested_date"], "2026-07-29")
        self.assertFalse(context["is_requested_date"])
        self.assertEqual(context["source"], "garmin")
        self.assertEqual(context["status"], "差")
        self.assertEqual(context["study_load"], "recovery")
        self.assertEqual(context["excluded_no_data_days"], 4)

    def test_build_dataset_maps_garmin_raw_into_body_os_models(self):
        from garmin_bodyos_365d import build_body_os_dataset

        raw = {
            "meta": {"start": "2026-07-28", "end": "2026-07-29"},
            "daily_summary": [
                {
                    "calendarDate": "2026-07-29",
                    "totalSteps": 8200,
                    "totalKilocalories": 2200,
                    "moderateIntensityMinutes": 35,
                    "vigorousIntensityMinutes": 8,
                    "floorsAscended": 10,
                    "averageStressLevel": 31,
                    "restingHeartRate": 58,
                    "bodyBatteryMostRecentValue": 72,
                    "averageSpo2": 97,
                }
            ],
            "sleep": [
                {
                    "dailySleepDTO": {
                        "calendarDate": "2026-07-29",
                        "sleepTimeSeconds": 25200,
                        "sleepScores": {"overall": {"value": 82}},
                    }
                }
            ],
            "heart_rate": [
                {"calendarDate": "2026-07-29", "restingHeartRate": 58}
            ],
            "stress": [
                {"calendarDate": "2026-07-29", "avgStressLevel": 31}
            ],
            "body_battery": [
                {"date": "2026-07-29", "charged": 45, "drained": 28}
            ],
            "hrv": [
                {
                    "hrvSummary": {
                        "calendarDate": "2026-07-29",
                        "lastNightAvg": 42,
                    }
                }
            ],
            "activities": [
                {
                    "activityId": 123,
                    "activityName": "Morning Run",
                    "activityType": {"typeKey": "running"},
                    "startTimeLocal": "2026-07-29 07:30:00",
                    "duration": 3600,
                    "distance": 10000,
                    "averageHR": 148,
                    "activityTrainingLoad": 126.5,
                }
            ],
        }

        dataset = build_body_os_dataset(raw)

        self.assertEqual(dataset["date_range"]["start"], "2026-07-29")
        self.assertEqual(dataset["date_range"]["raw_start"], "2026-07-28")
        self.assertEqual(dataset["date_range"]["end"], "2026-07-29")
        self.assertEqual(dataset["energy_daily"][0]["sleep_hours"], 7.0)
        self.assertEqual(dataset["energy_daily"][0]["sleep_quality"], 82)
        self.assertEqual(dataset["energy_daily"][0]["stress_level"], 31)
        self.assertEqual(dataset["energy_daily"][0]["resting_hr"], 58)
        self.assertEqual(dataset["energy_daily"][0]["hrv_ms"], 42)
        self.assertEqual(dataset["energy_daily"][0]["body_battery"], 72)
        self.assertEqual(dataset["energy_daily"][0]["mental_state"], "high")
        self.assertEqual(dataset["energy_daily"][0]["study_load"], "deep")
        self.assertEqual(dataset["training_logs"][0]["activity_type"], "running")
        self.assertEqual(dataset["body_metrics"][0]["resting_hr"], 58)
        self.assertEqual(dataset["daily_wellness"][0]["steps"], 8200)
        self.assertEqual(dataset["summary"]["training_log_count"], 1)
        self.assertEqual(dataset["today_energy_context"]["date"], "2026-07-29")
        self.assertEqual(dataset["today_training_context"]["date"], "2026-07-29")
        self.assertEqual(dataset["today_training_context"]["training_load"], "normal")

    def test_build_dataset_adds_training_policy_context(self):
        from garmin_bodyos_365d import build_body_os_dataset

        raw = {
            "meta": {"start": "2026-07-26", "end": "2026-07-29"},
            "daily_summary": [
                {"calendarDate": "2026-07-26", "totalSteps": 1000},
                {"calendarDate": "2026-07-27", "totalSteps": 1000},
                {"calendarDate": "2026-07-28", "totalSteps": 1000},
            ],
            "activities": [
                {
                    "activityId": 1,
                    "activityType": {"typeKey": "strength_training"},
                    "startTimeLocal": "2026-07-26 18:00:00",
                },
                {
                    "activityId": 2,
                    "activityType": {"typeKey": "strength_training"},
                    "startTimeLocal": "2026-07-27 18:00:00",
                },
                {
                    "activityId": 3,
                    "activityType": {"typeKey": "strength_training"},
                    "startTimeLocal": "2026-07-28 18:00:00",
                },
            ],
        }

        dataset = build_body_os_dataset(raw, valid_start="2026-07-26")

        context = dataset["today_training_context"]
        self.assertEqual(context["training_load"], "deload")
        self.assertTrue(
            any(item["code"] == "strength_3d_streak" for item in context["warnings"])
        )

    def test_build_dataset_combines_low_energy_with_training_policy(self):
        from garmin_bodyos_365d import build_body_os_dataset

        raw = {
            "meta": {"start": "2026-07-29", "end": "2026-07-29"},
            "daily_summary": [
                {
                    "calendarDate": "2026-07-29",
                    "totalSteps": 1000,
                    "bodyBatteryMostRecentValue": 18,
                    "averageStressLevel": 36,
                }
            ],
            "sleep": [
                {"dailySleepDTO": {"calendarDate": "2026-07-29", "sleepTimeSeconds": 24048}}
            ],
            "activities": [],
        }

        dataset = build_body_os_dataset(raw, valid_start="2026-07-29")

        self.assertEqual(dataset["today_energy_context"]["study_load"], "recovery")
        self.assertEqual(dataset["today_training_context"]["training_load"], "recovery")
        self.assertTrue(
            any(
                item["code"] == "low_body_energy_training"
                for item in dataset["today_training_context"]["warnings"]
            )
        )

    def test_summarize_dataset_uses_available_numeric_values(self):
        from garmin_bodyos_365d import summarize_dataset

        summary = summarize_dataset(
            {
                "energy_daily": [
                    {"sleep_hours": 7.0, "readiness_score": 80},
                    {"sleep_hours": None, "readiness_score": None},
                ],
                "training_logs": [{"activity_type": "running"}, {"activity_type": "other"}],
                "daily_wellness": [{"steps": 8000}, {"steps": None}],
            }
        )

        self.assertEqual(summary["avg_sleep_hours"], 7.0)
        self.assertEqual(summary["avg_readiness_score"], 80.0)
        self.assertEqual(summary["avg_steps"], 8000.0)
        self.assertEqual(summary["training_log_count"], 2)

    def test_build_dataset_respects_valid_start_calibration(self):
        from garmin_bodyos_365d import build_body_os_dataset

        raw = {
            "meta": {"start": "2025-07-30", "end": "2026-07-29"},
            "daily_summary": [
                {"calendarDate": "2025-12-10", "totalSteps": 100},
                {"calendarDate": "2025-12-11", "totalSteps": 8000},
            ],
            "sleep": [
                {
                    "dailySleepDTO": {
                        "calendarDate": "2025-12-10",
                        "sleepTimeSeconds": 0,
                    }
                },
                {
                    "dailySleepDTO": {
                        "calendarDate": "2025-12-11",
                        "sleepTimeSeconds": 28800,
                    }
                },
            ],
            "activities": [
                {
                    "activityId": 1,
                    "activityType": {"typeKey": "running"},
                    "startTimeLocal": "2025-12-10 07:30:00",
                },
                {
                    "activityId": 2,
                    "activityType": {"typeKey": "strength_training"},
                    "startTimeLocal": "2025-12-11 07:30:00",
                },
            ],
        }

        dataset = build_body_os_dataset(raw, valid_start="2025-12-11")

        self.assertEqual(
            dataset["date_range"],
            {
                "start": "2025-12-11",
                "end": "2026-07-29",
                "raw_start": "2025-07-30",
                "valid_start": "2025-12-11",
            },
        )
        self.assertEqual(dataset["summary"]["energy_days"], 1)
        self.assertEqual(dataset["summary"]["observation_days"], 1)
        self.assertEqual(dataset["summary"]["excluded_before_valid_start_days"], 1)
        self.assertEqual(dataset["daily_wellness"][0]["steps"], 8000)
        self.assertEqual(
            [item["garmin_activity_id"] for item in dataset["training_logs"]],
            ["2"],
        )

    def test_build_dataset_excludes_days_without_statistics_after_valid_start(self):
        from garmin_bodyos_365d import build_body_os_dataset

        raw = {
            "meta": {"start": "2025-12-11", "end": "2025-12-13"},
            "daily_summary": [
                {
                    "calendarDate": "2025-12-11",
                    "totalSteps": 9000,
                    "totalKilocalories": 2100,
                },
                {
                    "calendarDate": "2025-12-12",
                    "totalSteps": None,
                    "totalKilocalories": 2050,
                    "activeKilocalories": 0,
                    "averageStressLevel": -1,
                },
                {
                    "calendarDate": "2025-12-13",
                    "moderateIntensityMinutes": 20,
                },
            ],
            "sleep": [
                {"dailySleepDTO": {"calendarDate": "2025-12-12", "sleepTimeSeconds": None}}
            ],
            "activities": [],
        }

        dataset = build_body_os_dataset(raw, valid_start="2025-12-11")

        self.assertEqual(
            [item["date"] for item in dataset["energy_daily"]],
            ["2025-12-11", "2025-12-13"],
        )
        self.assertEqual(dataset["summary"]["observation_days"], 2)
        self.assertEqual(dataset["summary"]["excluded_no_data_days"], 1)
        self.assertEqual(dataset["calibration"]["excluded_no_data_days"], 1)


class BodyOSConfigTest(unittest.TestCase):
    def test_resolve_valid_start_reads_config_dict(self):
        from garmin_bodyos_365d import resolve_valid_start

        self.assertEqual(
            resolve_valid_start({"body_data": {"valid_start": "2026-01-01"}}),
            "2026-01-01",
        )

    def test_resolve_valid_start_falls_back_when_config_missing(self):
        from garmin_bodyos_365d import _FALLBACK_VALID_START, resolve_valid_start

        self.assertEqual(resolve_valid_start({}), _FALLBACK_VALID_START)
        self.assertEqual(
            resolve_valid_start({"body_data": {"valid_start": ""}}),
            _FALLBACK_VALID_START,
        )

    def test_load_body_os_config_reads_project_config_file(self):
        from garmin_bodyos_365d import BODY_OS_CONFIG_PATH, load_body_os_config

        config = load_body_os_config()
        self.assertTrue(BODY_OS_CONFIG_PATH.exists())
        self.assertIn("body_data", config)
        self.assertIn("valid_start", config["body_data"])

    def test_load_body_os_config_returns_empty_on_missing_file(self):
        import pathlib

        from garmin_bodyos_365d import load_body_os_config

        self.assertEqual(
            load_body_os_config(pathlib.Path("Z:/__no_such_file__.json")), {}
        )

    def test_build_dataset_default_uses_configured_valid_start(self):
        from unittest import mock

        import garmin_bodyos_365d

        raw = {
            "meta": {"start": "2025-12-11", "end": "2025-12-13"},
            "daily_summary": [
                {"calendarDate": "2025-12-11", "totalSteps": 9000},
                {"calendarDate": "2025-12-12", "totalSteps": 8000},
                {"calendarDate": "2025-12-13", "totalSteps": 7000},
            ],
            "activities": [],
        }
        with mock.patch.object(
            garmin_bodyos_365d,
            "load_body_os_config",
            return_value={"body_data": {"valid_start": "2025-12-13"}},
        ):
            dataset = garmin_bodyos_365d.build_body_os_dataset(raw)
        self.assertEqual(
            [item["date"] for item in dataset["energy_daily"]], ["2025-12-13"]
        )
        self.assertEqual(dataset["date_range"]["valid_start"], "2025-12-13")


if __name__ == "__main__":
    unittest.main(verbosity=2)
