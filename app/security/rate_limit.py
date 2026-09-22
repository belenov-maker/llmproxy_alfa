"""Rate limiting middleware — защита от перегрузки.

@business-rule BR-RL-01 При превышении лимита запросов — 429 Too Many Requests с Retry-After.
@business-rule BR-RL-02 Лимит: per-IP token bucket (default 5000 req/s, burst 200).
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class TokenBucket:
    """Token bucket для rate limiting."""

    rate: float  # токенов в секунду
    burst: int  # макс. накопленных токенов
    tokens: float = -1.0  # -1 = инициализировать из burst
    last_refill: float = field(default_factory=time.monotonic)

    def __post_init__(self):
        if self.tokens < 0:
            self.tokens = float(self.burst)

    def allow(self) -> bool:
        """Проверить, можно ли пропустить запрос."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        self.last_refill = now

        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


# ─── Pure ASGI middleware (без BaseHTTPMiddleware overhead) ──────


_SKIP_PATHS = {b"/health", b"/metrics"}

_429_BODY = b'{"detail":"Too Many Requests"}'


class RateLimitMiddleware:
    """Pure ASGI middleware для rate limiting per-IP.

    Не наследуется от BaseHTTPMiddleware — избегаем
    двойного буферизирования body и лишних task/coroutine.
    """

    def __init__(self, app, rate: float = 5000.0, burst: int = 200):
        self.app = app
        self.rate = rate
        self.burst = burst
        self._buckets: dict[str, TokenBucket] = defaultdict(
            lambda: TokenBucket(rate=self.rate, burst=self.burst)
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "").encode() if isinstance(scope.get("path"), str) else scope.get("raw_path", b"")
        if path in _SKIP_PATHS:
            await self.app(scope, receive, send)
            return

        # Извлекаем IP клиента
        client = scope.get("client")
        client_ip = client[0] if client else "unknown"
        bucket = self._buckets[client_ip]

        if bucket.allow():
            await self.app(scope, receive, send)
            return

        # 429 Too Many Requests
        retry_after = str(max(1, int(1.0 / self.rate)))
        await send({
            "type": "http.response.start",
            "status": 429,
            "headers": [
                [b"content-type", b"application/json"],
                [b"retry-after", retry_after.encode()],
                [b"content-length", str(len(_429_BODY)).encode()],
            ],
        })
        await send({
            "type": "http.response.body",
            "body": _429_BODY,
        })
