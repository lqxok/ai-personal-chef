from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from langchain.agents import create_agent
from langchain.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.config import Settings


SYSTEM_PROMPT = """
你是一名严谨、耐心、实用的 AI 私人厨师。你需要根据用户提供的文字或食材照片，
给出新手可以直接照着操作的菜谱，而不是只罗列菜名。

图片识别规则：
1. 只列出能够明确确认的食材，将结果分为“确认的食材”和“无法确认的食材”；
2. 看不清、被遮挡或无法判断的内容必须说明，不允许猜测；
3. 不要根据包装颜色、容器形状等信息臆测食材；
4. 图片信息不足时，先询问用户需要补充的信息。

菜谱搜索规则：
1. 需要推荐菜谱时，使用 Tavily 搜索可靠资料，再综合食材匹配度、营养、难度和耗时；
2. 不得伪造网站、搜索结果或参考链接；搜索不到可靠来源时必须明确说明；
3. 优先使用用户已有食材，减少额外购买；
4. 涉及过敏、变质食材、未熟肉蛋、海鲜或野生菌时，必须给出安全提醒。

默认回答结构：
## 一、食材识别结果
- 分别列出确认和无法确认的食材。

## 二、整体搭配建议
- 说明搭配思路和推荐理由。

## 三、推荐的三道菜
每道菜必须包含：
- 菜名、推荐理由、适合人数、预计耗时、难度；
- 主料、辅料和调味料的参考用量；
- 用户已有食材与缺少食材；
- 不少于 5 步的详细做法，每步说明火候、时间和熟度判断；
- 容易失败的地方、食品安全提醒和真实参考来源。

最后给出三道菜合理的烹饪顺序。用户指定数量、忌口、过敏、饮食目标或时间限制时，
优先遵守用户要求。不确定的信息必须明确标注，禁止编造。使用清晰的中文 Markdown。
""".strip()


def text_from_content(content: Any) -> str:
    """把普通文本或多模态消息转换为历史记录中可展示的文本。"""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


class PersonalChefAgent:
    """组合多模态模型、搜索工具和 LangGraph 会话记忆。"""

    def __init__(self, settings: Settings, checkpointer: AsyncSqliteSaver) -> None:
        model = ChatOpenAI(
            model=settings.model_name,
            base_url=settings.dashscope_base_url,
            api_key=settings.dashscope_api_key,
            temperature=0.2,
            max_tokens=4000,
            streaming=True,
            timeout=120,
            max_retries=2,
        )

        search = TavilySearch(
            max_results=5,
            topic="general",
        )

        self.graph = create_agent(
            model=model,
            tools=[search],
            system_prompt=SYSTEM_PROMPT,
            checkpointer=checkpointer,
        )
        self.checkpointer = checkpointer

    @staticmethod
    def _human_message(prompt: str, image_data: str | None = None) -> HumanMessage:
        if not image_data:
            return HumanMessage(content=prompt)

        return HumanMessage(
            content=[
                {"type": "image_url", "image_url": {"url": image_data}},
                {"type": "text", "text": prompt},
            ]
        )

    async def ask(
        self,
        prompt: str,
        thread_id: str,
        image_data: str | None = None,
    ) -> str:
        """非流式调用，供脚本和自动化测试使用。"""
        result = await self.graph.ainvoke(
            {"messages": [self._human_message(prompt, image_data)]},
            config={"configurable": {"thread_id": thread_id}},
        )
        return text_from_content(result["messages"][-1].content)

    async def stream_tokens(
        self,
        prompt: str,
        thread_id: str,
        image_data: str | None = None,
    ) -> AsyncIterator[str]:
        """只产出最终可展示的模型文本，HTTP 层负责封装为 SSE。"""
        message = self._human_message(prompt, image_data)

        async for chunk, _metadata in self.graph.astream(
            {"messages": [message]},
            config={"configurable": {"thread_id": thread_id}},
            stream_mode="messages",
        ):
            if not isinstance(chunk, AIMessageChunk):
                continue
            for block in chunk.content_blocks:
                if block.get("type") == "text" and block.get("text"):
                    yield block["text"]

    async def get_messages(self, thread_id: str) -> list[dict[str, str]]:
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await self.graph.aget_state(config)
        messages = snapshot.values.get("messages", []) if snapshot.values else []

        result: list[dict[str, str]] = []
        for message in messages:
            content = text_from_content(message.content)
            if not content:
                continue
            if isinstance(message, HumanMessage):
                result.append({"role": "user", "content": content})
            elif isinstance(message, AIMessage) and not message.tool_calls:
                result.append({"role": "assistant", "content": content})
        return result

    async def clear_messages(self, thread_id: str) -> None:
        await self.checkpointer.adelete_thread(thread_id)
