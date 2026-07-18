from __future__ import annotations

import argparse
import asyncio
import base64
import json
import mimetypes
import time
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agents.personal_chef import PersonalChefAgent, text_from_content
from app.config import DATA_DIR, PROJECT_ROOT, Settings
from evals.metrics import ingredient_metrics, recipe_completeness, summarize_results


DEFAULT_CASES_PATH = PROJECT_ROOT / "evals" / "cases.jsonl"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "artifacts" / "eval-results.json"
MAX_IMAGE_BYTES = 5 * 1024 * 1024


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} 不是有效 JSON") from exc
            required = {"id", "category", "prompt", "expect_search"}
            missing = required - case.keys()
            if missing:
                raise ValueError(f"{path}:{line_number} 缺少字段：{sorted(missing)}")
            cases.append(case)
    return cases


def _download_image_data_url(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "ai-personal-chef-eval/0.2"})
    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read(MAX_IMAGE_BYTES + 1)
        mime_type = response.headers.get_content_type()
    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError("评测图片超过 5 MB")
    if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
        guessed, _ = mimetypes.guess_type(url)
        mime_type = guessed or mime_type
    if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise ValueError(f"不支持的评测图片类型：{mime_type}")
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


async def image_data_for_case(case: dict[str, Any]) -> str | None:
    if not case.get("image_url"):
        return None
    return await asyncio.to_thread(_download_image_data_url, case["image_url"])


async def run_case(agent: PersonalChefAgent, case: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    first_token_at: float | None = None
    answer_parts: list[str] = []
    tool_attempts = 0
    tool_successes = 0
    tool_errors = 0

    image_data = await image_data_for_case(case)
    message = agent._human_message(case["prompt"], image_data)
    thread_id = f"eval-{case['id']}-{uuid.uuid4().hex[:8]}"

    async for event in agent.graph.astream_events(
        {"messages": [message]},
        config={"configurable": {"thread_id": thread_id}},
        version="v2",
    ):
        event_type = event.get("event")
        if event_type == "on_tool_start":
            tool_attempts += 1
        elif event_type == "on_tool_end":
            tool_successes += 1
        elif event_type == "on_tool_error":
            tool_errors += 1
        elif event_type == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            text = text_from_content(getattr(chunk, "content", ""))
            if text:
                if first_token_at is None:
                    first_token_at = time.perf_counter()
                answer_parts.append(text)

    answer = "".join(answer_parts)
    elapsed_ms = (time.perf_counter() - started) * 1000
    result: dict[str, Any] = {
        "id": case["id"],
        "category": case["category"],
        "expect_search": bool(case["expect_search"]),
        "tool_attempts": tool_attempts,
        "tool_successes": tool_successes,
        "tool_errors": tool_errors,
        "ttft_ms": round((first_token_at - started) * 1000, 2) if first_token_at else None,
        "total_latency_ms": round(elapsed_ms, 2),
        "answer": answer,
    }

    if case.get("expected_ingredients") is not None:
        result["ingredient"] = ingredient_metrics(
            answer,
            case["expected_ingredients"],
            case.get("ingredient_candidates", case["expected_ingredients"]),
        )
    if case.get("evaluate_recipe", False):
        result["recipe"] = recipe_completeness(
            answer,
            int(case.get("expected_recipe_count", 3)),
        )
    return result


async def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    cases = load_cases(args.cases)
    if args.category:
        cases = [case for case in cases if case["category"] in args.category]
    if args.skip_images:
        cases = [case for case in cases if not case.get("image_url")]
    if args.limit > 0:
        cases = cases[: args.limit]
    if not cases:
        raise ValueError("筛选后没有可运行的评测用例")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings = Settings.from_env()
    semaphore = asyncio.Semaphore(args.concurrency)
    results: list[dict[str, Any]] = []

    async with AsyncSqliteSaver.from_conn_string(str(DATA_DIR / "evals.db")) as checkpointer:
        await checkpointer.setup()
        agent = PersonalChefAgent(settings, checkpointer)

        async def guarded(case: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                try:
                    result = await run_case(agent, case)
                    print(
                        f"[{case['id']}] ok | TTFT={result['ttft_ms']} ms | "
                        f"tools={result['tool_successes']}/{result['tool_attempts']}",
                        flush=True,
                    )
                    return result
                except Exception as exc:
                    print(f"[{case['id']}] error | {type(exc).__name__}: {exc}", flush=True)
                    return {
                        "id": case["id"],
                        "category": case["category"],
                        "expect_search": bool(case["expect_search"]),
                        "error": f"{type(exc).__name__}: {exc}",
                    }

        results = list(await asyncio.gather(*(guarded(case) for case in cases)))

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "model": settings.model_name,
        "case_source": str(args.cases),
        "summary": summarize_results(results),
        "results": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 AI 私厨 Agent 评测集")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--limit", type=int, default=0, help="0 表示运行全部用例")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="SQLite Checkpointer 为保证确定性当前仅支持 1",
    )
    parser.add_argument("--category", action="append", help="可重复传入，只运行指定类别")
    parser.add_argument("--skip-images", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.concurrency != 1:
        raise SystemExit("当前评测使用单连接 SQLite Checkpointer，--concurrency 必须为 1")
    report = asyncio.run(evaluate(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"评测报告：{args.output.resolve()}")


if __name__ == "__main__":
    main()
