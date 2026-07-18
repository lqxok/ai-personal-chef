from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.agents.personal_chef import PersonalChefAgent
from app.models.schemas import ChatRequest, MessageHistory


logger = logging.getLogger(__name__)
router = APIRouter()

ThreadId = Annotated[
    str,
    Query(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9._:-]+$",
        description="浏览器会话标识",
    ),
]


def get_service(request: Request) -> PersonalChefAgent:
    return request.app.state.personal_chef


def encode_sse(event: str, payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n"


async def sse_stream(
    service: PersonalChefAgent,
    payload: ChatRequest,
    request: Request | None = None,
) -> AsyncIterator[str]:
    initial_status = "正在识别图片并整理食材……" if payload.image_data else "正在理解你的烹饪需求……"
    yield encode_sse("status", {"message": initial_status})
    yield encode_sse("status", {"message": "Agent 正在规划菜谱，必要时会联网搜索……"})

    try:
        async for token in service.stream_tokens(
            prompt=payload.message,
            thread_id=payload.thread_id,
            image_data=payload.image_data,
        ):
            if request is not None and await request.is_disconnected():
                logger.info("客户端断开 SSE：thread_id=%s", payload.thread_id)
                return
            yield encode_sse("token", {"text": token})

        yield encode_sse("done", {"ok": True})
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Agent 调用失败：thread_id=%s", payload.thread_id)
        yield encode_sse(
            "error",
            {
                "code": "AGENT_ERROR",
                "message": "私厨暂时没有响应，请稍后重试。如果问题持续，请检查模型和搜索服务配置。",
            },
        )


@router.post("/chat/stream", summary="流式生成私厨建议")
async def chat_stream(
    payload: ChatRequest,
    request: Request,
) -> StreamingResponse:
    return StreamingResponse(
        sse_stream(get_service(request), payload, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/chat/messages",
    response_model=MessageHistory,
    summary="读取当前会话历史",
)
async def get_chat_messages(
    thread_id: ThreadId,
    request: Request,
) -> MessageHistory:
    messages = await get_service(request).get_messages(thread_id)
    return MessageHistory(messages=messages)


@router.delete("/chat/messages", summary="清空当前会话")
async def clear_chat_messages(
    thread_id: ThreadId,
    request: Request,
) -> dict[str, bool]:
    await get_service(request).clear_messages(thread_id)
    return {"success": True}
