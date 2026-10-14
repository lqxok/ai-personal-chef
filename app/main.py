#这是 Python 的特殊导入，用来更灵活地处理类型标注。
# 这样可以避免在运行时检查类型，从而提高性能。不过，这也会导致在开发时出现类型错误，因此在开发时需要特别注意。
#这行不会启动服务，也不会调用 AI，主要服务于类型检查和代码可读性。
from __future__ import annotations

#导入 Python 自带的日志模块：程序运行后可以输出：2026-07-18 19:30:00 | INFO | app.main | AI 私厨服务启动
import logging
#导入一个用于管理“异步资源生命周期”的工具。
#这个项目启动时要：打开 SQLite 数据库。创建 Agent。启动网站。网站关闭时关闭数据库。asynccontextmanager 就是帮助完成这个过程的。
from contextlib import asynccontextmanager
#导入 FastAPI 的核心类
from fastapi import FastAPI, Request
#FileResponse 用于把一个文件发送给浏览器。项目访问 / 时，需要把 index.html 返回给浏览器，所以使用它。
from fastapi.responses import FileResponse, JSONResponse
#用于提供静态文件，浏览器请求 /static/styles.css 时，就是由 StaticFiles 返回文件。
from fastapi.staticfiles import StaticFiles
#这是 LangGraph 提供的异步 SQLite 会话存储工具。它会保存：用户说过什么AI 回答了什么当前对话属于哪个 thread_id；Agent 当前的会话状态
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
#从自己项目里导入 AI 私厨 Agent。
from app.agents.personal_chef import PersonalChefAgent
#从自己项目里导入聊天路由。导入聊天接口，并给它起一个当前文件使用的名字：chat_router
from app.api.v1.chat import router as chat_router
#从自己项目里导入配置文件。导入配置文件，配置文件包含：数据目录、数据库路径、静态文件目录、设置类
from app.config import DATA_DIR, DB_PATH, STATIC_DIR, Settings
from app.ratelimit import (
    DAILY_WINDOW_SECONDS,
    MINUTE_WINDOW_SECONDS,
    RateLimiter,
    client_ip,
)

# Configure logging
#这段代码设置日志格式。
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

#生命周期，这一段负责管理应用的启动和关闭。
@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings = Settings.from_env()
    # 限流器：分钟级（每 IP）+ 每日级（每 IP / 全局）。放在 state 上，中间件读取。
    app.state.settings = settings
    app.state.minute_limiter = RateLimiter(MINUTE_WINDOW_SECONDS)
    app.state.daily_ip_limiter = RateLimiter(DAILY_WINDOW_SECONDS)
    app.state.daily_total_limiter = RateLimiter(DAILY_WINDOW_SECONDS)
#这行打开 SQLite Checkpointer。
    async with AsyncSqliteSaver.from_conn_string(str(DB_PATH)) as checkpointer:
        #初始化 Checkpointer 需要的数据表。await 表示：这个操作需要等待，但等待时可以把执行权交给服务器，让服务器处理其他异步任务。
        await checkpointer.setup()
        #这里创建了真正的 AI 私厨 Agent。传入settings参数让agent知道使用哪个模型，模型API地址、API key等信息。传入checkpointer参数让agent知道如何保存和恢复会话状态。
        app.state.personal_chef = PersonalChefAgent(settings, checkpointer)
        logging.getLogger(__name__).info(
            "AI 私厨服务启动，模型：%s，限流：%d 次/分、每 IP 每日 %d 次、全局每日 %d 次",
            settings.model_name,
            settings.rate_limit_per_minute,
            settings.daily_limit_per_ip,
            settings.daily_limit_total,
        )
        yield
#创建整个 Web 应用。
#定义FastAPI实例， FastAPI实例包含路由和静态文件夹,路由是定义在app.include_router()中的，静态文件夹是定义在app.mount()中的
app = FastAPI(
    title="AI Personal Chef API",
    version="0.2.0",
    description="支持食材图片识别、联网搜索、会话记忆与 SSE 流式输出的多模态私厨 Agent。",
    lifespan=lifespan,
)

# 将路由添加到FastAPI实例中，路由是定义在app.include_router()中的，静态文件夹是定义在app.mount()中的
app.include_router(chat_router, prefix="/api/v1", tags=["chat"])
# 将静态文件夹添加到FastAPI实例中，静态文件夹是定义在app.mount()中的
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 会产生大模型调用成本、需要计「每日配额」的接口
_COST_PATHS = {"/api/v1/chat/stream"}
# 容器健康检查不参与限流
_EXEMPT_PATHS = {"/api/health"}


def _too_many(detail: str) -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": detail})


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """三层限流：分钟级（每 IP）+ 每日级（每 IP / 全局）。

    只为业务接口计数；静态资源、首页与健康检查直接放行。
    Demo 部署在公网且无鉴权，靠这三层把模型成本锁住。
    """
    settings: Settings | None = getattr(request.app.state, "settings", None)
    path = request.url.path
    if settings is None or not path.startswith("/api/") or path in _EXEMPT_PATHS:
        return await call_next(request)

    ip = client_ip(request)

    minute: RateLimiter | None = getattr(request.app.state, "minute_limiter", None)
    if minute and not minute.allow(ip, settings.rate_limit_per_minute):
        logging.getLogger(__name__).warning("触发分钟级限流：ip=%s path=%s", ip, path)
        return _too_many("请求过于频繁，请稍后再试")

    if path in _COST_PATHS:
        daily_ip: RateLimiter | None = getattr(request.app.state, "daily_ip_limiter", None)
        if daily_ip and not daily_ip.allow(ip, settings.daily_limit_per_ip):
            logging.getLogger(__name__).warning("触发每日限流（单 IP）：ip=%s", ip)
            return _too_many("今天的体验额度已用完，请明天再来")

        daily_total: RateLimiter | None = getattr(
            request.app.state, "daily_total_limiter", None
        )
        if daily_total and not daily_total.allow("__total__", settings.daily_limit_total):
            logging.getLogger(__name__).warning("触发每日限流（全局）")
            return _too_many("今日演示额度已用尽，请稍后再试")

    return await call_next(request)


#定义根路径路由，根路径路由是定义在app.get()中的，根路径路由是包含在app.include_router()中的，根路径路由是包含在app.mount()中的
@app.get("/", include_in_schema=False)
async def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/api/health", tags=["system"], summary="服务健康检查")
async def health(request: Request) -> dict[str, object]:
    settings: Settings | None = getattr(request.app.state, "settings", None)
    payload: dict[str, object] = {"status": "ok", "service": "ai-personal-chef"}
    if settings is not None:
        # 暴露限流配置，便于确认线上是否已生效（该接口本身豁免限流）
        payload["rate_limit"] = {
            "per_minute": settings.rate_limit_per_minute,
            "per_ip_per_day": settings.daily_limit_per_ip,
            "total_per_day": settings.daily_limit_total,
        }
    return payload


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8001, reload=True)


#FastAPI 已经提前为 app 创建了一个官方的 state 区域，专门让开发者保存自定义对象。