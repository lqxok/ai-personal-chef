"""限流测试：滑动窗口、客户端 IP 解析、中间件行为。

注意：本仓库 CI 用 `python -m unittest discover -s tests` 收集用例，
所以这里必须写成 `unittest.TestCase` 子类（pytest 风格的裸函数不会被收集）。
"""

from __future__ import annotations

import time
import unittest

from app.ratelimit import DAILY_WINDOW_SECONDS, MINUTE_WINDOW_SECONDS, RateLimiter, client_ip

_COST_PATH = "/api/v1/chat/stream"


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


class RateLimiterTests(unittest.TestCase):
    def test_allow_within_limit_then_block(self) -> None:
        limiter = RateLimiter(window=60.0)
        self.assertTrue(limiter.allow("1.1.1.1", 2))
        self.assertTrue(limiter.allow("1.1.1.1", 2))
        self.assertFalse(limiter.allow("1.1.1.1", 2))
        # 不同 key 互不影响
        self.assertTrue(limiter.allow("2.2.2.2", 2))

    def test_window_expiry_releases_quota(self) -> None:
        limiter = RateLimiter(window=0.05)
        self.assertTrue(limiter.allow("1.1.1.1", 1))
        self.assertFalse(limiter.allow("1.1.1.1", 1))
        time.sleep(0.06)  # 等窗口滑过去
        self.assertTrue(limiter.allow("1.1.1.1", 1))

    def test_non_positive_limit_means_unlimited(self) -> None:
        limiter = RateLimiter(window=60.0)
        for _ in range(50):
            self.assertTrue(limiter.allow("1.1.1.1", 0))

    def test_reset_clears_all_buckets(self) -> None:
        limiter = RateLimiter(window=60.0)
        limiter.allow("1.1.1.1", 1)
        limiter.reset()
        self.assertTrue(limiter.allow("1.1.1.1", 1))


class ClientIpTests(unittest.TestCase):
    def test_prefers_x_forwarded_for(self) -> None:
        """Render 前面有反向代理，必须读 X-Forwarded-For 才能区分访客。"""
        request = _FakeRequest(
            headers={"X-Forwarded-For": "9.9.9.9, 10.0.0.1"}, host="10.0.0.1"
        )
        self.assertEqual(client_ip(request), "9.9.9.9")

    def test_falls_back_to_direct_client(self) -> None:
        self.assertEqual(client_ip(_FakeRequest(host="8.8.8.8")), "8.8.8.8")

    def test_handles_missing_client(self) -> None:
        self.assertEqual(client_ip(_FakeRequest()), "unknown")


class RateLimitMiddlewareTests(unittest.TestCase):
    """直接给 app.state 装配限流器；不用 with，避免触发 lifespan 去连 SQLite。"""

    def _build_client(self, *, per_minute: int, per_ip: int, total: int = 1000):
        from fastapi.testclient import TestClient

        from app.config import Settings
        from app.main import app

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

    def test_minute_limit_returns_429(self) -> None:
        client = self._build_client(per_minute=2, per_ip=100)
        self.assertEqual(client.get("/api/health").status_code, 200)  # 健康检查豁免
        for _ in range(2):
            self.assertNotEqual(
                client.post(_COST_PATH, json={"message": "hi"}).status_code, 429
            )
        self.assertEqual(client.post(_COST_PATH, json={"message": "hi"}).status_code, 429)

    def test_daily_limit_per_ip_returns_429(self) -> None:
        client = self._build_client(per_minute=100, per_ip=2)
        for _ in range(2):
            self.assertNotEqual(
                client.post(_COST_PATH, json={"message": "hi"}).status_code, 429
            )
        self.assertEqual(client.post(_COST_PATH, json={"message": "hi"}).status_code, 429)

    def test_health_exposes_rate_limit_config(self) -> None:
        """健康检查暴露限流配置，便于线上确认是否生效，且自身不受限流影响。"""
        client = self._build_client(per_minute=7, per_ip=8, total=9)
        body = client.get("/api/health").json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(
            body["rate_limit"], {"per_minute": 7, "per_ip_per_day": 8, "total_per_day": 9}
        )

    def test_global_daily_limit_returns_429(self) -> None:
        """即使伪造 X-Forwarded-For 换 IP，全局上限也会兜住。"""
        client = self._build_client(per_minute=1000, per_ip=1000, total=2)
        first = {"X-Forwarded-For": "1.1.1.1"}
        for _ in range(2):
            self.assertNotEqual(
                client.post(_COST_PATH, json={"message": "hi"}, headers=first).status_code,
                429,
            )
        # 换个「IP」继续刷：单 IP 配额没到，但全局配额已耗尽
        second = {"X-Forwarded-For": "2.2.2.2"}
        self.assertEqual(
            client.post(_COST_PATH, json={"message": "hi"}, headers=second).status_code, 429
        )


if __name__ == "__main__":
    unittest.main()
