"""需要真实 API Key 的模型连通性检查。"""

from langchain_openai import ChatOpenAI

from app.config import Settings


settings = Settings.from_env()
model = ChatOpenAI(
    model=settings.model_name,
    base_url=settings.dashscope_base_url,
    api_key=settings.dashscope_api_key,
    temperature=0.2,
)

response = model.invoke("请只回复一句话：模型连接成功。")
print(response.content)
