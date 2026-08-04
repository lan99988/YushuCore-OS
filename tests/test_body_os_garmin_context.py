import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_PARENT = os.path.join(WORKSPACE, "02_执行引擎（Engine）")
if ENGINE_PARENT not in sys.path:
    sys.path.insert(0, ENGINE_PARENT)

from 输入解析引擎.handlers import body_os  # noqa: E402


class BodyOSGarminContextTest(unittest.TestCase):
    def test_controller_message_includes_garmin_summary_when_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "body_os_garmin_summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "date_range": {"start": "2025-07-30", "end": "2026-07-29"},
                        "summary": {
                            "energy_days": 365,
                            "training_log_count": 91,
                            "excluded_no_data_days": 4,
                            "activity_type_counts": {"running": 54, "strength": 32},
                            "avg_sleep_hours": 4.01,
                            "avg_readiness_score": 38.54,
                            "avg_steps": 8544.14,
                        },
                        "today_energy_context": {
                            "date": "2026-07-28",
                            "requested_date": "2026-07-29",
                            "is_requested_date": False,
                            "status": "差",
                            "mental_state_label": "耗竭",
                            "study_load_label": "恢复/维护",
                            "energy_coefficient": 0.65,
                            "body_battery": 18,
                            "body_battery_score": 18,
                            "reason": "身体可用能量18，今天先保护恢复。",
                        },
                        "today_training_context": {
                            "date": "2026-07-29",
                            "training_load": "deload",
                            "training_load_label": "降载",
                            "recommendation": "今天训练建议降载，优先恢复、灵活性或 Zone2。",
                            "scope_note": "当前仅基于 activityType 判断训练频率，尚未细分肌群。",
                            "warnings": [
                                {
                                    "code": "strength_3d_streak",
                                    "message": "连续3天力量训练，建议降低训练量。",
                                }
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            old_path = body_os.GARMIN_SUMMARY_PATH
            body_os.GARMIN_SUMMARY_PATH = summary_path
            try:
                result = body_os.handle_body_os("#身体 今天适合练什么", dry_run=True)
            finally:
                body_os.GARMIN_SUMMARY_PATH = old_path

        self.assertIn("Garmin近一年", result["message"])
        self.assertIn("训练91次", result["message"])
        self.assertIn("跑步54次", result["message"])
        self.assertIn("力量32次", result["message"])
        self.assertIn("无统计日已排除4天", result["message"])
        self.assertIn("最新有效Garmin日：2026-07-28", result["message"])
        self.assertIn("精神状态：耗竭", result["message"])
        self.assertIn("学习负载：恢复/维护", result["message"])
        self.assertIn("身体可用能量18", result["message"])
        self.assertIn("训练建议：降载", result["message"])
        self.assertIn("连续3天力量训练", result["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
