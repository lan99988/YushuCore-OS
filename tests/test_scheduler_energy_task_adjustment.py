import os
import sys
import unittest


WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEDULER_DIR = os.path.join(WORKSPACE, "02_执行引擎（Engine）", "每日排程引擎")
if SCHEDULER_DIR not in sys.path:
    sys.path.insert(0, SCHEDULER_DIR)

import daily_scheduler  # noqa: E402


class SchedulerEnergyTaskAdjustmentTest(unittest.TestCase):
    def test_recovery_keeps_p0_and_defers_noncritical_high_energy_tasks(self):
        tasks = [
            {"title": "必须提交", "priority": "P0-重要紧急", "energy": "高", "weight": 100},
            {"title": "高强度刷题", "priority": "P1-重要不紧急", "energy": "高", "weight": 80},
            {"title": "整理笔记", "priority": "P2-紧急不重要", "energy": "低", "weight": 60},
        ]

        result = daily_scheduler.adjust_tasks_for_energy_policy(
            tasks, {"study_load": "recovery"}, dry_run=True,
        )

        kept_titles = [item["title"] for item in result["tasks"]]
        overflow_titles = [item["title"] for item in result["overflow"]]
        self.assertIn("必须提交", kept_titles)
        self.assertIn("整理笔记", kept_titles)
        self.assertIn("高强度刷题", overflow_titles)
        # control_level 由 config 决定, dry_run 避免写 Base
        self.assertEqual(result["control_level"], 2)

    def test_deep_load_boosts_high_energy_tasks(self):
        tasks = [{"title": "论文硬骨头", "priority": "P1-重要不紧急", "energy": "高", "weight": 80}]

        result = daily_scheduler.adjust_tasks_for_energy_policy(
            tasks, {"study_load": "deep"}, dry_run=True,
        )

        self.assertGreater(result["tasks"][0]["weight"], 80)


if __name__ == "__main__":
    unittest.main(verbosity=2)
