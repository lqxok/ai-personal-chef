"""需要真实 API Key 的 Tavily 连通性检查。"""

from langchain_tavily import TavilySearch

from app.config import Settings


settings = Settings.from_env()
search = TavilySearch(
    max_results=3,
    topic="general",
)

result = search.invoke({"query": "番茄炒蛋 家常做法"})
print(result)
