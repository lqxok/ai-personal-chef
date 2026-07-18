"""需要真实 API Key 的完整 Agent 连通性检查。"""

import asyncio

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agents.personal_chef import PersonalChefAgent
from app.config import DATA_DIR, DB_PATH, Settings


async def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(DB_PATH)) as checkpointer:
        await checkpointer.setup()
        agent = PersonalChefAgent(Settings.from_env(), checkpointer)
        answer = await agent.ask(
            "我有鸡蛋、西红柿和豆腐，两个人吃，请推荐三道菜。",
            thread_id="agent-smoke-test",
        )
        print(answer)


if __name__ == "__main__":
    asyncio.run(main())
