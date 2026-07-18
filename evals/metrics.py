from __future__ import annotations

import math
import re
from collections.abc import Iterable
from statistics import mean, median
from typing import Any


INGREDIENT_ALIASES: dict[str, tuple[str, ...]] = {
    "番茄": ("番茄", "西红柿"),
    "鸡蛋": ("鸡蛋", "蛋类"),
    "土豆": ("土豆", "马铃薯"),
    "西兰花": ("西兰花", "绿花椰菜", "青花菜"),
    "胡萝卜": ("胡萝卜", "红萝卜"),
    "彩椒": ("彩椒", "甜椒", "灯笼椒", "青椒", "红椒", "黄椒"),
    "鸡胸肉": ("鸡胸肉", "鸡胸", "生鸡肉"),
    "蘑菇": ("蘑菇", "口蘑", "白蘑菇"),
    "洋葱": ("洋葱",),
    "茄子": ("茄子",),
    "黄瓜": ("黄瓜", "青瓜"),
    "豆腐": ("豆腐",),
    "虾": ("虾", "虾仁"),
    "牛肉": ("牛肉",),
    "猪肉": ("猪肉",),
    "菠菜": ("菠菜",),
    "白菜": ("白菜",),
    "芹菜": ("芹菜",),
    "南瓜": ("南瓜",),
    "玉米": ("玉米",),
}


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def confirmed_ingredient_section(answer: str) -> str:
    """只截取模型回答中的“确认食材”区域，避免菜谱配料造成假阳性。"""
    start = re.search(r"确认(?:的)?食材\s*[：:]?", answer, flags=re.IGNORECASE)
    if not start:
        return ""

    tail = answer[start.end() :]
    endings = [
        r"(?:^|\n)\s*#{1,6}\s*无法确认",
        r"(?:^|\n)\s*[-*]?\s*无法确认(?:的)?食材\s*[：:]?",
        r"(?:^|\n)\s*#{1,6}\s*(?:二|2)[、.\s]",
        r"(?:^|\n)\s*#{1,6}\s*整体搭配",
        r"(?:^|\n)\s*#{1,6}\s*推荐",
    ]
    end_positions = []
    for pattern in endings:
        match = re.search(pattern, tail, flags=re.IGNORECASE)
        if match:
            end_positions.append(match.start())
    return tail[: min(end_positions)] if end_positions else tail


def detect_ingredients(answer: str, candidates: Iterable[str]) -> set[str]:
    section = _compact(confirmed_ingredient_section(answer))
    if not section:
        return set()

    detected: set[str] = set()
    for ingredient in candidates:
        aliases = INGREDIENT_ALIASES.get(ingredient, (ingredient,))
        if any(_compact(alias) in section for alias in aliases):
            detected.add(ingredient)
    return detected


def ingredient_metrics(
    answer: str,
    expected: Iterable[str],
    candidates: Iterable[str],
) -> dict[str, Any]:
    expected_set = set(expected)
    predicted = detect_ingredients(answer, candidates)
    true_positive = len(predicted & expected_set)
    false_positive = len(predicted - expected_set)
    false_negative = len(expected_set - predicted)
    precision = true_positive / (true_positive + false_positive) if predicted else 0.0
    recall = true_positive / len(expected_set) if expected_set else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "predicted": sorted(predicted),
        "expected": sorted(expected_set),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "exact_match": predicted == expected_set,
    }


def recipe_completeness(answer: str, expected_recipe_count: int = 3) -> dict[str, Any]:
    """用稳定、可解释的规则检查菜谱字段；该指标衡量格式完整性而非口味。"""
    step_count = len(re.findall(r"(?m)^\s*(?:步骤\s*)?\d+[.)、]\s*\S+", answer))
    source_links = re.findall(r"https?://[^\s)>]+", answer)
    checks = {
        "dish_name": bool(
            re.search(
                r"菜名|^#{2,6}\s*(?:第?[一二三四五\d]+道[：:]?)?\s*\S+",
                answer,
                flags=re.MULTILINE,
            )
        ),
        "recommendation_reason": "推荐理由" in answer,
        "servings": bool(re.search(r"适合人数|\d+\s*[-—至到]?\s*\d*\s*人份?", answer)),
        "estimated_time": bool(re.search(r"预计耗时|烹饪时间|\d+\s*分钟", answer)),
        "difficulty": "难度" in answer,
        "ingredient_quantities": bool(
            re.search(r"\d+(?:\.\d+)?\s*(?:克|g|kg|毫升|ml|个|只|勺|片|根|碗)", answer, re.IGNORECASE)
        ),
        "owned_and_missing": "已有食材" in answer and "缺少食材" in answer,
        "detailed_steps": step_count >= max(5, expected_recipe_count * 5),
        "heat_time_doneness": (
            bool(re.search(r"大火|中火|小火|火候", answer))
            and bool(re.search(r"\d+\s*(?:分钟|秒)", answer))
            and bool(re.search(r"熟|断生|变色|金黄|透明|沸腾|收汁", answer))
        ),
        "failure_and_safety": bool(re.search(r"失败|易错|注意", answer)) and "安全" in answer,
        "real_source": bool(source_links),
        "cooking_order": "烹饪顺序" in answer,
    }
    passed = sum(checks.values())
    return {
        "checks": checks,
        "passed": passed,
        "total": len(checks),
        "score": round(passed / len(checks), 4),
        "step_count": step_count,
        "source_count": len(source_links),
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [item for item in results if not item.get("error")]
    ingredient_rows = [item["ingredient"] for item in successful if item.get("ingredient")]
    recipe_rows = [item["recipe"] for item in successful if item.get("recipe")]
    ttft_values = [float(item["ttft_ms"]) for item in successful if item.get("ttft_ms") is not None]

    true_positive = sum(row["true_positive"] for row in ingredient_rows)
    false_positive = sum(row["false_positive"] for row in ingredient_rows)
    false_negative = sum(row["false_negative"] for row in ingredient_rows)
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    attempts = sum(item.get("tool_attempts", 0) for item in successful)
    successes = sum(item.get("tool_successes", 0) for item in successful)
    expected_tool = [item for item in successful if item.get("expect_search")]
    expected_tool_met = sum(item.get("tool_successes", 0) > 0 for item in expected_tool)

    return {
        "case_count": len(results),
        "successful_case_count": len(successful),
        "error_count": len(results) - len(successful),
        "ingredient_recognition": {
            "evaluated_cases": len(ingredient_rows),
            "micro_precision": round(precision, 4),
            "micro_recall": round(recall, 4),
            "micro_f1": round(f1, 4),
            "exact_set_accuracy": round(
                sum(row["exact_match"] for row in ingredient_rows) / len(ingredient_rows), 4
            )
            if ingredient_rows
            else None,
        },
        "tool_calls": {
            "attempts": attempts,
            "successes": successes,
            "success_rate": round(successes / attempts, 4) if attempts else None,
            "expected_search_cases": len(expected_tool),
            "expected_search_coverage": round(expected_tool_met / len(expected_tool), 4)
            if expected_tool
            else None,
        },
        "recipe_completeness": {
            "evaluated_cases": len(recipe_rows),
            "average_score": round(mean(row["score"] for row in recipe_rows), 4)
            if recipe_rows
            else None,
        },
        "first_token_latency_ms": {
            "evaluated_cases": len(ttft_values),
            "mean": round(mean(ttft_values), 2) if ttft_values else None,
            "median": round(median(ttft_values), 2) if ttft_values else None,
            "p95": round(_percentile(ttft_values, 0.95), 2) if ttft_values else None,
        },
    }
