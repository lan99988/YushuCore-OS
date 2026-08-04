import os
import sys
import unittest


WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(WORKSPACE, "08_工具脚本（Tools）", "身体管理")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)


class EnergyPolicyTest(unittest.TestCase):
    def test_low_body_energy_is_a_hard_brake(self):
        from energy_policy import derive_daily_mental_state

        result = derive_daily_mental_state(
            {
                "body_battery_score": 18,
                "readiness_score": 61,
                "sleep_hours": 6.68,
                "stress_level": 36,
            }
        )

        self.assertEqual(result["mental_state"], "depleted")
        self.assertEqual(result["study_load"], "recovery")
        self.assertEqual(result["status"], "差")
        self.assertEqual(result["energy_coefficient"], 0.65)
        self.assertIn("身体可用能量18", result["reason"])

    def test_study_load_tiers(self):
        from energy_policy import derive_daily_mental_state

        self.assertEqual(
            derive_daily_mental_state(
                {
                    "body_battery_score": 75,
                    "readiness_score": 70,
                    "sleep_hours": 7.4,
                    "stress_level": 32,
                }
            )["study_load"],
            "deep",
        )
        self.assertEqual(
            derive_daily_mental_state(
                {
                    "body_battery_score": 48,
                    "readiness_score": 55,
                    "sleep_hours": 6.6,
                    "stress_level": 42,
                }
            )["study_load"],
            "standard",
        )
        self.assertEqual(
            derive_daily_mental_state(
                {
                    "body_battery_score": 32,
                    "readiness_score": 58,
                    "sleep_hours": 6.4,
                    "stress_level": 40,
                }
            )["study_load"],
            "light",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
