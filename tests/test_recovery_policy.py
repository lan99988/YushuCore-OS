import os
import sys
import unittest


WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(WORKSPACE, "08_工具脚本（Tools）", "身体管理")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)


class RecoveryPolicyTest(unittest.TestCase):
    def test_low_body_energy_forces_recovery_priority(self):
        from recovery_policy import derive_recovery_policy

        result = derive_recovery_policy(
            {"body_battery_score": 18, "sleep_hours": 6.7, "stress_level": 36},
            {"training_load": "normal", "current_7d_training_load": 100},
        )

        self.assertEqual(result["recovery_state"], "protect")
        self.assertEqual(result["recommended_training"], "recovery")
        self.assertTrue(any(item["code"] == "low_body_energy" for item in result["warnings"]))

    def test_high_training_load_with_poor_sleep_recommends_deload(self):
        from recovery_policy import derive_recovery_policy

        result = derive_recovery_policy(
            {"body_battery_score": 55, "sleep_hours": 5.5, "stress_level": 50},
            {"training_load": "caution", "current_7d_training_load": 500},
        )

        self.assertEqual(result["recovery_state"], "strained")
        self.assertEqual(result["recommended_training"], "deload")

    def test_normal_recovery_allows_standard_training(self):
        from recovery_policy import derive_recovery_policy

        result = derive_recovery_policy(
            {"body_battery_score": 72, "sleep_hours": 7.3, "stress_level": 35},
            {"training_load": "normal"},
        )

        self.assertEqual(result["recovery_state"], "ready")
        self.assertEqual(result["recommended_training"], "normal")


if __name__ == "__main__":
    unittest.main(verbosity=2)
