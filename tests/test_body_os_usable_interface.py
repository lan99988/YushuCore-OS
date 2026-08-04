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


class BodyOSUsableInterfaceTest(unittest.TestCase):
    def test_training_entry_returns_parsed_manual_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_path = body_os.MANUAL_TRAINING_LOG_PATH
            body_os.MANUAL_TRAINING_LOG_PATH = Path(tmp) / "manual_training_log.json"
            try:
                result = body_os.handle_body_os("#训练 力量 卧推 60kgx8x3 45分钟", dry_run=True)
            finally:
                body_os.MANUAL_TRAINING_LOG_PATH = old_path

        self.assertIn("训练记录草稿", result["message"])
        self.assertIn("力量", result["message"])
        self.assertIn("总容量1440", result["message"])

    def test_recovery_entry_uses_summary_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "today_energy_context": {"body_battery_score": 18, "sleep_hours": 6.7},
                        "today_training_context": {"training_load": "normal"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            old_summary = body_os.GARMIN_SUMMARY_PATH
            body_os.GARMIN_SUMMARY_PATH = summary_path
            try:
                result = body_os.handle_body_os("#恢复 今天怎么恢复", dry_run=True)
            finally:
                body_os.GARMIN_SUMMARY_PATH = old_summary

        self.assertIn("恢复建议", result["message"])
        self.assertIn("保护恢复", result["message"])

    def test_nutrition_entry_returns_minimum_loop(self):
        result = body_os.handle_body_os("#营养 今天怎么吃", dry_run=True)

        self.assertIn("营养建议", result["message"])
        self.assertIn("蛋白质", result["message"])
        self.assertIn("暂不使用复杂食物数据库", result["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
