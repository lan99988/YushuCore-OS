import json
import os
import sys
import unittest


WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_DIR = os.path.join(WORKSPACE, "04_数据中心（Data）", "数据模型（Schema）")
SKILL_DIR = os.path.join(WORKSPACE, "01_Skill能力库（Skills）")
ENGINE_PARENT = os.path.join(WORKSPACE, "02_执行引擎（Engine）")
if ENGINE_PARENT not in sys.path:
    sys.path.insert(0, ENGINE_PARENT)


def _load_schema(category, filename):
    path = os.path.join(SCHEMA_DIR, category, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _field_names(schema):
    return {field["name"] for field in schema["fields"]}


class BodyOSSchemaContractTest(unittest.TestCase):
    def test_training_log_schema_exists_with_body_os_contract_fields(self):
        schema = _load_schema("01_核心执行", "TrainingLog.json")

        self.assertEqual(schema["model"], "TrainingLog")
        self.assertIsNone(schema["feishu_table"])
        self.assertIn("yushu_11_力量塑形_StrengthSystem", schema["source_skill"])
        self.assertTrue({
            "date",
            "activity_type",
            "session_name",
            "duration_min",
            "intensity",
            "rpe",
            "strength_focus",
            "exercises",
            "distance_km",
            "avg_hr",
            "training_load",
            "garmin_activity_id",
            "source",
            "notes",
        }.issubset(_field_names(schema)))

    def test_nutrition_log_schema_keeps_phase_one_small(self):
        schema = _load_schema("01_核心执行", "NutritionLog.json")

        self.assertEqual(schema["model"], "NutritionLog")
        self.assertIsNone(schema["feishu_table"])
        self.assertIn("yushu_12_营养管理_NutritionSystem", schema["source_skill"])
        self.assertTrue({
            "date",
            "protein_g",
            "water_ml",
            "supplements",
            "adherence",
            "source",
            "notes",
        }.issubset(_field_names(schema)))

    def test_body_metrics_schema_supports_long_term_body_trends(self):
        schema = _load_schema("02_成长管理", "BodyMetrics.json")

        self.assertEqual(schema["model"], "BodyMetrics")
        self.assertIsNone(schema["feishu_table"])
        self.assertIn("yushu_14_身体分析_BodyAnalytics", schema["source_skill"])
        self.assertTrue({
            "date",
            "weight_kg",
            "body_fat_percent",
            "waist_cm",
            "chest_cm",
            "hip_cm",
            "upper_arm_cm",
            "thigh_cm",
            "resting_hr",
            "hrv_ms",
            "source",
            "notes",
        }.issubset(_field_names(schema)))

    def test_energy_schema_is_upgraded_for_recovery_readiness(self):
        schema = _load_schema("01_核心执行", "Energy.json")

        self.assertEqual(schema["model"], "Energy")
        self.assertIn("yushu_10_身体总管_BodyController", schema["source_skill"])
        self.assertTrue({
            "sleep_hours",
            "sleep_quality",
            "soreness",
            "readiness_score",
            "stress_level",
            "resting_hr",
            "hrv_ms",
            "body_battery",
            "recovery_note",
        }.issubset(_field_names(schema)))


class BodyOSSkillContractTest(unittest.TestCase):
    EXPECTED_SKILLS = [
        "yushu_10_身体总管_BodyController",
        "yushu_11_力量塑形_StrengthSystem",
        "yushu_12_营养管理_NutritionSystem",
        "yushu_13_恢复管理_RecoverySystem",
        "yushu_14_身体分析_BodyAnalytics",
    ]

    def test_body_os_skills_exist_with_required_sections(self):
        for dirname in self.EXPECTED_SKILLS:
            with self.subTest(dirname=dirname):
                path = os.path.join(SKILL_DIR, dirname, "SKILL.md")
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()

                self.assertIn("---", content)
                self.assertIn("## 基础信息", content)
                self.assertIn("## 功能定位", content)
                self.assertIn("## 触发方式", content)
                self.assertIn("## 数据", content)
                self.assertIn("## 测试", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
