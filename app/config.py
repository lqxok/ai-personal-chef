from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "personal_chef.db"
STATIC_DIR = PROJECT_ROOT / "app" / "static"

load_dotenv(PROJECT_ROOT / ".env")


def _int_env(name: str, default: int) -> int:
    """读整数环境变量；缺失或非法时用默认值。"""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True, slots=True)
class Settings:
    """应用启动所需的外部服务配置。"""

    dashscope_api_key: str
    dashscope_base_url: str
    model_name: str
    tavily_api_key: str
    # 限流：Demo 无鉴权，靠这三层把模型成本锁住（<=0 表示不限）
    rate_limit_per_minute: int = 10
    daily_limit_per_ip: int = 20
    daily_limit_total: int = 200

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            dashscope_api_key=os.getenv("DASHSCOPE_API_KEY", "").strip(),
            dashscope_base_url=os.getenv(
                "DASHSCOPE_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ).strip(),
            model_name=os.getenv("MODEL_NAME", "qwen3.5-plus").strip(),
            tavily_api_key=os.getenv("TAVILY_API_KEY", "").strip(),
            rate_limit_per_minute=_int_env("RATE_LIMIT_PER_MINUTE", 10),
            daily_limit_per_ip=_int_env("DAILY_LIMIT_PER_IP", 20),
            daily_limit_total=_int_env("DAILY_LIMIT_TOTAL", 200),
        )

        missing = [
            name
            for name, value in {
                "DASHSCOPE_API_KEY": settings.dashscope_api_key,
                "TAVILY_API_KEY": settings.tavily_api_key,
            }.items()
            if not value
        ]
        if missing:
            joined = "、".join(missing)
            raise RuntimeError(f"缺少环境变量：{joined}")

        if not settings.dashscope_base_url.startswith(("http://", "https://")):
            raise RuntimeError("DASHSCOPE_BASE_URL 必须是有效的 HTTP(S) 地址")

        return settings
