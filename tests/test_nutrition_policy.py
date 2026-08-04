import os
import sys
import unittest


WORKSPACE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(WORKSPACE, "08_工具脚本（Tools）", "身体管理")
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)


class NutritionPolicyTest(unittest.TestCase):
    def test_minimum_nutrition_guidance_uses_protein_and_weight(self):
        from nutrition_policy import derive_nutrition_policy

        result = derive_nutrition_policy(
            body_weight_kg=70,
            goal_priority=["recomposition", "fat_loss", "muscle_gain"],
        )

        self.assertEqual(result["mode"], "minimum_loop")
        self.assertEqual(result["protein_target_g"], 126)
        self.assertIn("蛋白质", result["recommendation"])
        self.assertFalse(result["uses_food_database"])

    def test_training_day_adds_protein_timing_hint(self):
        from nutrition_policy import derive_nutrition_policy

        result = derive_nutrition_policy(body_weight_kg=70, training_context={"training_load": "normal"})

        self.assertTrue(any(item["code"] == "training_day_protein" for item in result["hints"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
