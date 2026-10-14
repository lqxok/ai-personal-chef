"""限流单元测试：滑动窗口 + 客户端 IP 解析（含中间件行为）。"""

from __future__ import annotations

import time

from app.ratelimit import RateLimiter, client_ip


class _Headers(dict):
    """模拟 Starlette 的大小写不敏感 headers。"""

    def get(self, key, default=""):  # type: ignore[override]
        return super().get(key.lower(), default)


class _Client:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    def __init__(self, headers: dict | None = None, host: str | None = None) -> None:
        self.headers = _Headers({k.lower(): v for k, v in (headers or {}).items()})
        self.client = _Client(host) if host else None


# ---------- RateLimiter ----------


def test_allow_within_limit_then_block():
    limiter = RateLimiter(window=60.0)
    assert limiter.allow("1.1.1.1", 2) is True
    assert limiter.allow("1.1.1.1", 2) is True
    assert limiter.allow("1.1.1.1", 2) is False
    # 不同 key 互不影响
    assert limiter.allow("2.2.2.2", 2) is True


def test_window_expiry_releases_quota():
    limiter = RateLimiter(window=0.05)
    assert limiter.allow("1.1.1.1", 1) is True
    assert limiter.allow("1.1.1.1", 1) is False
    time.sleep(0.06)  # 等窗口滑过去
    assert limiter.allow("1.1.1.1", 1) is True


def test_non_positive_limit_means_unlimited():
    limiter = RateLimiter(window=60.0)
    for _ in range(50):
        assert limiter.allow("1.1.1.1", 0) is True


def test_reset_clears_all_buckets():
    limiter = RateLimiter(window=60.0)
    limiter.allow("1.1.1.1", 1)
    limiter.reset()
    assert limiter.allow("1.1.1.1", 1) is True


# ---------- client_ip ----------


def test_client_ip_prefers_x_forwarded_for():
    """Render 前面有反向代理，必须读 X-Forwarded-For 才能区分访客。"""
    request = _FakeRequest(headers={"X-Forwarded-For": "9.9.9.9, 10.0.0.1"}, host="10.0.0.1")
    assert client_ip(request) == "9.9.9.9"


def test_client_ip_falls_back_to_direct_client():
    assert client_ip(_FakeRequest(host="8.8.8.8")) == "8.8.8.8"


def test_client_ip_handles_missing_client():
    assert client_ip(_FakeRequest()) == "unknown"


# ---------- 中间件 ----------

_COST_PATH = "/api/v1/chat/stream"


def _build_client(*, per_minute: int, per_ip: int, total: int = 1000):
    """装配限流器后返回 TestClient（不用 with，避免触发 lifespan 去连 SQLite）。"""
    from fastapi.testclient import TestClient

    from app.config import Settings
    from app.main import app
    from app.ratelimit import DAILY_WINDOW_SECONDS, MINUTE_WINDOW_SECONDS

    app.state.settings = Settings(
        dashscope_api_key="test",
        dashscope_base_url="https://example.com/v1",
        model_name="test-model",
        tavily_api_key="test",
        rate_limit_per_minute=per_minute,
        daily_limit_per_ip=per_ip,
        daily_limit_total=total,
    )
    app.state.minute_limiter = RateLimiter(MINUTE_WINDOW_SECONDS)
    app.state.daily_ip_limiter = RateLimiter(DAILY_WINDOW_SECONDS)
    app.state.daily_total_limiter = RateLimiter(DAILY_WINDOW_SECONDS)
    # raise_server_exceptions=False：未装配 Agent，业务逻辑会 500，这里只关心限流与否
    return TestClient(app, raise_server_exceptions=False)


def test_middleware_minute_limit_returns_429():
    client = _build_client(per_minute=2, per_ip=100)
    assert client.get("/api/health").status_code == 200  # 健康检查豁免
    for _ in range(2):
        assert client.post(_COST_PATH, json={"message": "hi"}).status_code != 429
    assert client.post(_COST_PATH, json={"message": "hi"}).status_code == 429


def test_middleware_daily_limit_per_ip_returns_429():
    client = _build_client(per_minute=100, per_ip=2)
    for _ in range(2):
        assert client.post(_COST_PATH, json={"message": "hi"}).status_code != 429
    assert client.post(_COST_PATH, json={"message": "hi"}).status_code == 429


def test_middleware_global_daily_limit_returns_429():
    """即使伪造 X-Forwarded-For 换 IP，全局上限也会兜住。"""
    client = _build_client(per_minute=1000, per_ip=1000, total=2)
    headers = {"X-Forwarded-For": "1.1.1.1"}
    assert client.post(_COST_PATH, json={"message": "hi"}, headers=headers).status_code != 429
    assert client.post(_COST_PATH, json={"message": "hi"}, headers=headers).status_code != 429
    # 换个「IP」继续刷：单 IP 配额没到，但全局配额已耗尽
    other = {"X-Forwarded-For": "2.2.2.2"}
    assert client.post(_COST_PATH, json={"message": "hi"}, headers=other).status_code == 429
