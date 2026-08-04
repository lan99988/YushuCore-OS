import os
import sys
import types
import unittest


WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(WORKSPACE, "08_工具脚本（Tools）", "身体管理")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

from garmin_sync_7d import decide_today_focus, fetch_garmin_7d, map_to_body_os  # noqa: E402


class GarminBodyOSMappingTest(unittest.TestCase):
    def test_maps_garmin_snapshot_into_body_os_fields(self):
        raw = {
            "sleep": [
                {
                    "calendarDate": "2026-07-28",
                    "sleepTimeSeconds": 25200,
                    "sleepScore": 82,
                }
            ],
            "activities": [
                {
                    "activityId": 123,
                    "activityName": "Morning Run",
                    "activityType": {"typeKey": "running"},
                    "startTimeLocal": "2026-07-28 07:30:00",
                    "duration": 3600,
                    "distance": 10000,
                    "averageHR": 148,
                    "trainingLoad": 126.5,
                }
            ],
            "heart_rate": [
                {"calendarDate": "2026-07-28", "restingHeartRate": 58}
            ],
            "stress": [
                {"calendarDate": "2026-07-28", "avgStressLevel": 31}
            ],
            "body_battery": [
                {"calendarDate": "2026-07-28", "charged": 72}
            ],
        }

        mapped = map_to_body_os(raw)

        self.assertEqual(mapped["date_range"]["end"], "2026-07-28")
        self.assertEqual(mapped["energy"]["sleep_hours"], 7.0)
        self.assertEqual(mapped["energy"]["sleep_quality"], 82)
        self.assertEqual(mapped["energy"]["resting_hr"], 58)
        self.assertEqual(mapped["energy"]["stress_level"], 31)
        self.assertEqual(mapped["energy"]["body_battery"], 72)
        self.assertEqual(mapped["training_logs"][0]["activity_type"], "running")
        self.assertEqual(mapped["training_logs"][0]["distance_km"], 10.0)
        self.assertEqual(mapped["training_logs"][0]["duration_min"], 60.0)

    def test_decision_recommends_recovery_when_readiness_is_low(self):
        mapped = {
            "energy": {
                "sleep_hours": 4.5,
                "stress_level": 82,
                "body_battery": 24,
                "readiness_score": 30,
            },
            "training_logs": [],
        }

        decision = decide_today_focus(mapped)

        self.assertEqual(decision["recommendation"], "recovery")
        self.assertIn("睡眠", decision["reason"])

    def test_maps_cn_nested_sleep_and_activity_training_load_fields(self):
        raw = {
            "sleep": [
                {
                    "dailySleepDTO": {
                        "calendarDate": "2026-07-29",
                        "sleepTimeSeconds": 28800,
                        "sleepScores": {"overall": {"value": 76}},
                    }
                }
            ],
            "activities": [
                {
                    "activityId": 456,
                    "activityName": "CN Ride",
                    "activityType": {"typeKey": "cycling"},
                    "startTimeLocal": "2026-07-29 18:00:00",
                    "duration": 1800,
                    "distance": 12000,
                    "averageHR": 121,
                    "activityTrainingLoad": 25.5,
                }
            ],
            "heart_rate": [],
            "stress": [],
            "body_battery": [],
        }

        mapped = map_to_body_os(raw)

        self.assertEqual(mapped["energy"]["sleep_hours"], 8.0)
        self.assertEqual(mapped["energy"]["sleep_quality"], 76)
        self.assertEqual(mapped["training_logs"][0]["training_load"], 25.5)

    def test_fetch_uses_cn_flag_and_tokenstore_from_environment(self):
        calls = {}

        class FakeGarmin:
            def __init__(self, **kwargs):
                calls["init"] = kwargs

            def login(self, tokenstore=None):
                calls["tokenstore"] = tokenstore

            def get_sleep_data(self, day):
                return {"calendarDate": day}

            def get_activities(self, start, limit):
                return []

            def get_heart_rates(self, day):
                return {"calendarDate": day}

            def get_stress_data(self, day):
                return {"calendarDate": day}

            def get_body_battery(self, day):
                return {"calendarDate": day}

        original_module = sys.modules.get("garminconnect")
        sys.modules["garminconnect"] = types.SimpleNamespace(Garmin=FakeGarmin)
        old_is_cn = os.environ.get("GARMIN_IS_CN")
        old_token_dir = os.environ.get("GARMIN_TOKEN_DIR")
        os.environ["GARMIN_IS_CN"] = "true"
        os.environ["GARMIN_TOKEN_DIR"] = r"C:\Users\26326\.garminconnect"
        try:
            import garmin_sync_7d

            garmin_sync_7d.fetch_garmin_7d("2632610394@qq.com")
        finally:
            if original_module is None:
                sys.modules.pop("garminconnect", None)
            else:
                sys.modules["garminconnect"] = original_module
            if old_is_cn is None:
                os.environ.pop("GARMIN_IS_CN", None)
            else:
                os.environ["GARMIN_IS_CN"] = old_is_cn
            if old_token_dir is None:
                os.environ.pop("GARMIN_TOKEN_DIR", None)
            else:
                os.environ["GARMIN_TOKEN_DIR"] = old_token_dir

        self.assertEqual(calls["init"], {"is_cn": True})
        self.assertEqual(calls["tokenstore"], r"C:\Users\26326\.garminconnect")

    def test_fetch_falls_back_to_cn_gc_api_when_garminconnect_rejects_cn_token(self):
        calls = {}

        class FakeGarmin:
            def __init__(self, **kwargs):
                calls["init"] = kwargs

            def login(self, tokenstore=None):
                calls["tokenstore"] = tokenstore
                raise RuntimeError("Failed to retrieve social profile")

        class FakeCnGcApiClient:
            def __init__(self, profile_dir=None):
                calls["profile_dir"] = profile_dir

            def fetch_7d(self, email=None):
                calls["fallback_email"] = email
                return {
                    "meta": {"account": email, "source": "garmin_cn_gc_api"},
                    "sleep": [],
                    "activities": [],
                    "heart_rate": [],
                    "stress": [],
                    "body_battery": [],
                }

        original_module = sys.modules.get("garminconnect")
        sys.modules["garminconnect"] = types.SimpleNamespace(Garmin=FakeGarmin)
        import garmin_sync_7d

        old_client = garmin_sync_7d.GarminCnGcApiClient
        old_is_cn = os.environ.get("GARMIN_IS_CN")
        old_token_dir = os.environ.get("GARMIN_TOKEN_DIR")
        old_profile = os.environ.get("GARMIN_CHROME_PROFILE")
        os.environ["GARMIN_IS_CN"] = "true"
        os.environ["GARMIN_TOKEN_DIR"] = r"C:\Users\26326\.garminconnect"
        os.environ["GARMIN_CHROME_PROFILE"] = r"C:\Users\26326\.garminconnect\chrome-login-profile"
        garmin_sync_7d.GarminCnGcApiClient = FakeCnGcApiClient
        try:
            raw = fetch_garmin_7d("2632610394@qq.com")
        finally:
            garmin_sync_7d.GarminCnGcApiClient = old_client
            if original_module is None:
                sys.modules.pop("garminconnect", None)
            else:
                sys.modules["garminconnect"] = original_module
            if old_is_cn is None:
                os.environ.pop("GARMIN_IS_CN", None)
            else:
                os.environ["GARMIN_IS_CN"] = old_is_cn
            if old_token_dir is None:
                os.environ.pop("GARMIN_TOKEN_DIR", None)
            else:
                os.environ["GARMIN_TOKEN_DIR"] = old_token_dir
            if old_profile is None:
                os.environ.pop("GARMIN_CHROME_PROFILE", None)
            else:
                os.environ["GARMIN_CHROME_PROFILE"] = old_profile

        self.assertEqual(raw["meta"]["source"], "garmin_cn_gc_api")
        self.assertEqual(calls["init"], {"is_cn": True})
        self.assertEqual(calls["tokenstore"], r"C:\Users\26326\.garminconnect")
        self.assertEqual(
            calls["profile_dir"],
            r"C:\Users\26326\.garminconnect\chrome-login-profile",
        )
        self.assertEqual(calls["fallback_email"], "2632610394@qq.com")


if __name__ == "__main__":
    unittest.main(verbosity=2)
