import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(WORKSPACE, "08_工具脚本（Tools）", "身体管理")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)


class TrainingLogTest(unittest.TestCase):
    def test_parse_strength_entry_extracts_exercises_and_volume(self):
        from training_log import parse_training_entry

        entry = parse_training_entry(
            "#训练 力量 卧推 60kgx8x3 深蹲 80kgx5x5 45分钟",
            today="2026-07-29",
        )

        self.assertEqual(entry["date"], "2026-07-29")
        self.assertEqual(entry["activity_type"], "strength")
        self.assertEqual(entry["duration_min"], 45)
        self.assertEqual(entry["total_volume"], 60 * 8 * 3 + 80 * 5 * 5)
        self.assertEqual(entry["exercises"][0]["name"], "卧推")
        self.assertEqual(entry["exercises"][1]["sets"], 5)

    def test_parse_running_entry_extracts_distance_and_duration(self):
        from training_log import parse_training_entry

        entry = parse_training_entry("#训练 跑步 5公里 32分钟", today="2026-07-29")

        self.assertEqual(entry["activity_type"], "running")
        self.assertEqual(entry["distance_km"], 5)
        self.assertEqual(entry["duration_min"], 32)

    def test_append_training_entry_persists_json_list(self):
        from training_log import append_training_entry, parse_training_entry

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "manual_training_log.json"
            entry = parse_training_entry("#训练 力量 引体向上 0kgx6x4", today="2026-07-29")
            append_training_entry(path, entry)

            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["source"], "manual")


if __name__ == "__main__":
    unittest.main(verbosity=2)
