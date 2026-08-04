import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEDULER_DIR = os.path.join(WORKSPACE, "02_执行引擎（Engine）", "每日排程引擎")
if SCHEDULER_DIR not in sys.path:
    sys.path.insert(0, SCHEDULER_DIR)

import daily_scheduler  # noqa: E402


class DailySchedulerGarminEnergyTest(unittest.TestCase):
    def test_load_energy_context_keeps_garmin_runtime_fields_for_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "_energy_status.json"
            status_path.write_text(
                json.dumps(
                    {
                        "date": "2026-07-29",
                        "status": "差",
                        "source": "garmin",
                        "body_battery": 18,
                        "study_load": "recovery",
                        "energy_coefficient": 0.65,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            old_path = daily_scheduler.ENERGY_STATUS_FILE
            daily_scheduler.ENERGY_STATUS_FILE = str(status_path)
            try:
                context = daily_scheduler.load_energy_context(today="2026-07-29")
            finally:
                daily_scheduler.ENERGY_STATUS_FILE = old_path

        self.assertEqual(context["status"], "差")
        self.assertEqual(context["source"], "garmin")
        self.assertEqual(context["study_load"], "recovery")
        self.assertEqual(context["energy_coefficient"], 0.65)

    def test_energy_multiplier_uses_garmin_coefficient_when_no_manual_override(self):
        self.assertEqual(
            daily_scheduler.resolve_energy_multiplier(
                {"status": "差", "energy_coefficient": 0.65},
                {},
            ),
            0.65,
        )
        self.assertEqual(
            daily_scheduler.resolve_energy_multiplier(
                {"status": "差", "energy_coefficient": 0.65},
                {"精力系数": 0.9},
            ),
            0.9,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
