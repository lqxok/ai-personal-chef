"""需要真实 API Key 的会话记忆检查。"""

import asyncio

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agents.personal_chef import PersonalChefAgent
from app.config import DATA_DIR, DB_PATH, Settings


async def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    async with AsyncSqliteSaver.from_conn_string(str(DB_PATH)) as checkpointer:
        await checkpointer.setup()
        chef = PersonalChefAgent(Settings.from_env(), checkpointer)

        first = await chef.ask(
            "我有鸡蛋、西红柿和豆腐，请推荐三道菜。",
            thread_id="memory-smoke-test",
        )
        print("第一次回答：")
        print(first)

        second = await chef.ask(
            "请详细展开你刚才推荐的第一道菜。",
            thread_id="memory-smoke-test",
        )
        print("\n第二次回答：")
        print(second)


if __name__ == "__main__":
    asyncio.run(main())
