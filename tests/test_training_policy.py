import os
import sys
import unittest


WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(WORKSPACE, "08_工具脚本（Tools）", "身体管理")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)


class TrainingPolicyTest(unittest.TestCase):
    def test_three_consecutive_strength_days_recommends_deload(self):
        from training_policy import derive_training_policy

        result = derive_training_policy(
            [
                {"date": "2026-07-26", "activity_type": "strength"},
                {"date": "2026-07-27", "activity_type": "strength"},
                {"date": "2026-07-28", "activity_type": "strength"},
            ],
            today="2026-07-29",
        )

        self.assertEqual(result["training_load"], "deload")
        self.assertTrue(result["strength_consecutive_days"] >= 3)
        self.assertTrue(any(item["code"] == "strength_3d_streak" for item in result["warnings"]))
        self.assertIn("肌群级", result["scope_note"])

    def test_strength_within_48_hours_adds_recovery_warning(self):
        from training_policy import derive_training_policy

        result = derive_training_policy(
            [
                {"date": "2026-07-27", "activity_type": "running"},
                {"date": "2026-07-28", "activity_type": "strength"},
            ],
            today="2026-07-29",
        )

        self.assertEqual(result["training_load"], "caution")
        self.assertTrue(any(item["code"] == "strength_48h_repeat" for item in result["warnings"]))

    def test_training_load_spike_over_40_percent_warns(self):
        from training_policy import derive_training_policy

        logs = []
        for day in range(8, 15):
            logs.append(
                {
                    "date": f"2026-07-{day:02d}",
                    "activity_type": "running",
                    "training_load": 50,
                }
            )
        for day in range(15, 22):
            logs.append(
                {
                    "date": f"2026-07-{day:02d}",
                    "activity_type": "running",
                    "training_load": 100,
                }
            )

        result = derive_training_policy(logs, today="2026-07-22")

        self.assertEqual(result["training_load"], "caution")
        self.assertTrue(any(item["code"] == "training_load_spike_40pct" for item in result["warnings"]))
        self.assertGreater(result["current_7d_training_load"], result["previous_7d_training_load"])

    def test_no_recent_training_keeps_normal_policy(self):
        from training_policy import derive_training_policy

        result = derive_training_policy([], today="2026-07-29")

        self.assertEqual(result["training_load"], "normal")
        self.assertEqual(len(result["warnings"]), 0)
        self.assertIn("today_muscle_groups", result)
        self.assertIn("today_muscle_volume", result)
        self.assertIn("muscle_group_risk", result)

    def test_depleted_body_energy_recommends_training_recovery(self):
        from training_policy import derive_training_policy

        result = derive_training_policy(
            [],
            today="2026-07-29",
            energy_context={"study_load": "recovery", "body_battery_score": 18},
        )

        self.assertEqual(result["training_load"], "recovery")
        self.assertTrue(any(item["code"] == "low_body_energy_training" for item in result["warnings"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
