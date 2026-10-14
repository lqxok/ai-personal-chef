"""轻量限流：进程内存里的滑动窗口计数（单实例部署够用）。

私厨 Demo 部署在公网、没有登录，如果完全不限流，任何人拿到地址都能消耗你的
百炼（DashScope）额度。因此这里做三层限制：

- **分钟级（每 IP）**：防突发刷接口；
- **每日级（每 IP）**：单个访客的成本上限；
- **每日级（全局）**：所有访客加起来的硬上限——即使有人伪造 `X-Forwarded-For`
  换 IP，也烧不穿这一层。

限流用「滑动窗口」而不是固定窗口，是为了避开临界点的双倍突发。
"""

from __future__ import annotations

import time
from collections import deque

MINUTE_WINDOW_SECONDS = 60.0
DAILY_WINDOW_SECONDS = 86_400.0


class RateLimiter:
    """滑动窗口限流器：每个 key（如客户端 IP）在窗口内最多放行 limit 次。"""

    def __init__(self, window: float) -> None:
        self._window = window
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, limit: int) -> bool:
        """允许则记一次并返回 True；超限返回 False；limit <= 0 表示不限。"""
        if limit <= 0:
            return True
        now = time.monotonic()
        bucket = self._hits.setdefault(key, deque())
        cutoff = now - self._window
        while bucket and bucket[0] <= cutoff:  # 丢掉窗口外的旧记录
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


def client_ip(request) -> str:
    """取客户端 IP。

    Render 这类平台的服务器前面有反向代理，`request.client.host` 会是代理的地址，
    真实访客 IP 在 `X-Forwarded-For` 里；取不到时再退回直连地址。
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    client = getattr(request, "client", None)
    return client.host if client else "unknown"
