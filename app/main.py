from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.agents.personal_chef import PersonalChefAgent
from app.api.v1.chat import router as chat_router
from app.config import DATA_DIR, DB_PATH, STATIC_DIR, Settings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings = Settings.from_env()

    async with AsyncSqliteSaver.from_conn_string(str(DB_PATH)) as checkpointer:
        await checkpointer.setup()
        app.state.personal_chef = PersonalChefAgent(settings, checkpointer)
        logging.getLogger(__name__).info("AI 私厨服务启动，模型：%s", settings.model_name)
        yield


app = FastAPI(
    title="AI Personal Chef API",
    version="0.2.0",
    description="支持食材图片识别、联网搜索、会话记忆与 SSE 流式输出的多模态私厨 Agent。",
    lifespan=lifespan,
)

app.include_router(chat_router, prefix="/api/v1", tags=["chat"])
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health", tags=["system"], summary="服务健康检查")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "ai-personal-chef"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8001, reload=True)
