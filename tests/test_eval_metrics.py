import unittest

from evals.metrics import (
    confirmed_ingredient_section,
    ingredient_metrics,
    recipe_completeness,
    summarize_results,
)


class IngredientMetricTests(unittest.TestCase):
    def test_extracts_only_confirmed_section(self) -> None:
        answer = """## 一、食材识别结果
### 确认的食材
- 西红柿
- 鸡蛋
### 无法确认的食材
- 一个绿色包装
## 二、推荐
- 可以补充土豆
"""
        section = confirmed_ingredient_section(answer)
        self.assertIn("西红柿", section)
        self.assertNotIn("土豆", section)

    def test_ingredient_metric_supports_aliases_and_false_positives(self) -> None:
        answer = "## 确认的食材\n- 西红柿\n- 土豆\n## 无法确认的食材\n- 无"
        metrics = ingredient_metrics(
            answer,
            expected=["番茄"],
            candidates=["番茄", "土豆", "鸡蛋"],
        )
        self.assertEqual(metrics["true_positive"], 1)
        self.assertEqual(metrics["false_positive"], 1)
        self.assertEqual(metrics["false_negative"], 0)


class RecipeMetricTests(unittest.TestCase):
    def test_completeness_is_explainable(self) -> None:
        answer = """## 菜名：番茄炒蛋
- 推荐理由：快手
- 适合人数：2 人
- 预计耗时：15 分钟
- 难度：简单
- 已有食材：番茄 200 克、鸡蛋 2 个
- 缺少食材：盐 2 克
1. 中火加热 1 分钟。
2. 炒蛋 2 分钟至熟。
3. 下番茄炒 2 分钟至出汁。
4. 小火调味 1 分钟。
5. 收汁 1 分钟，蛋液完全凝固。
- 易错与食品安全：鸡蛋必须熟透。
- 参考：https://example.com/recipe
## 烹饪顺序
先备菜再炒制。
"""
        result = recipe_completeness(answer, expected_recipe_count=1)
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["step_count"], 5)

    def test_summary_aggregates_requested_metrics(self) -> None:
        summary = summarize_results(
            [
                {
                    "ingredient": {
                        "true_positive": 1,
                        "false_positive": 0,
                        "false_negative": 0,
                        "exact_match": True,
                    },
                    "recipe": {"score": 0.75},
                    "tool_attempts": 1,
                    "tool_successes": 1,
                    "expect_search": True,
                    "ttft_ms": 100,
                }
            ]
        )
        self.assertEqual(summary["ingredient_recognition"]["micro_f1"], 1.0)
        self.assertEqual(summary["tool_calls"]["success_rate"], 1.0)
        self.assertEqual(summary["recipe_completeness"]["average_score"], 0.75)
        self.assertEqual(summary["first_token_latency_ms"]["p95"], 100)


if __name__ == "__main__":
    unittest.main()
