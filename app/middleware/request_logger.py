"""Request-logging middleware — аудит каждого HTTP-запроса.

@business-process Аудит и трассировка операций
@business-rule BR-LOG-04 Каждый HTTP-запрос (кроме /health, /metrics) логируется с request_id.
@business-rule BR-LOG-05 X-Request-ID header добавляется в каждый ответ.

Pure ASGI middleware (без BaseHTTPMiddleware overhead).
"""

from __future__ import annotations

import logging
import time
import uuid

from app.context import request_id_var

logger = logging.getLogger(__name__)

# Пути, которые не логируем (шум от мониторинга)
_SKIP_PATHS = {"/health", "/metrics"}


class RequestLoggerMiddleware:
    """Pure ASGI middleware: request_id + structured access log.

    Генерирует UUID4 request_id для каждого запроса, сохраняет в ContextVar,
    добавляет X-Request-ID в response headers, логирует method/path/status/latency.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Генерируем request_id и сохраняем в ContextVar
        rid = uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)

        try:
            if path in _SKIP_PATHS:
                # Для health/metrics — просто прокидываем request_id в header, не логируем
                await self._pass_with_header(scope, receive, send, rid)
                return

            # Собираем метаданные запроса
            method = scope.get("method", "?")
            client = scope.get("client")
            client_ip = client[0] if client else "-"
            headers_raw = scope.get("headers", [])
            user_agent = "-"
            for name, value in headers_raw:
                if name == b"user-agent":
                    user_agent = value.decode("utf-8", errors="replace")
                    break

            start = time.monotonic()
            status_code = 0

            async def send_wrapper(message):
                nonlocal status_code
                if message["type"] == "http.response.start":
                    status_code = message.get("status", 0)
                    # Добавляем X-Request-ID в response headers
                    headers = list(message.get("headers", []))
                    headers.append([b"x-request-id", rid.encode()])
                    message = {**message, "headers": headers}
                await send(message)

            await self.app(scope, receive, send_wrapper)

            latency_ms = (time.monotonic() - start) * 1000

            logger.info(
                "%s %s %d %.1fms",
                method,
                path,
                status_code,
                latency_ms,
                extra={
                    "event": "http_request",
                    "method": method,
                    "path": path,
                    "status": status_code,
                    "client_ip": client_ip,
                    "latency_ms": round(latency_ms, 1),
                    "user_agent": user_agent,
                },
            )
        finally:
            request_id_var.reset(token)

    async def _pass_with_header(self, scope, receive, send, rid: str):
        """Пропустить запрос, добавив только X-Request-ID header."""

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append([b"x-request-id", rid.encode()])
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
