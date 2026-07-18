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


@dataclass(frozen=True, slots=True)
class Settings:
    """应用启动所需的外部服务配置。"""

    dashscope_api_key: str
    dashscope_base_url: str
    model_name: str
    tavily_api_key: str

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
