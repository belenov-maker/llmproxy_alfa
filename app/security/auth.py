"""API-key аутентификация.

@business-process Контроль доступа к PD-Proxy
@business-rule BR-AUTH-01 Запрос без валидного X-API-Key → 403.
@business-rule BR-AUTH-02 /health и /metrics доступны без ключа.
"""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.config import load_systems_config

logger = logging.getLogger(__name__)

# Эндпоинты, доступные без аутентификации
_PUBLIC_PATHS = frozenset({"/health", "/metrics", "/docs", "/openapi.json", "/redoc"})


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Middleware для проверки API-ключа из заголовка X-API-Key."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint,
    ) -> Response:
        # Публичные эндпоинты — без авторизации
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        api_key = request.headers.get("X-API-Key")
        if not api_key:
            logger.warning("Запрос без API-ключа: %s %s", request.method, request.url.path)
            return JSONResponse(
                status_code=403,
                content={"detail": "X-API-Key header required"},
            )

        # Проверяем ключ в systems.yaml
        systems_config = load_systems_config()
        systems = systems_config.get("systems", {})

        valid = False
        for _sys_id, sys_cfg in systems.items():
            if isinstance(sys_cfg, dict) and sys_cfg.get("api_key") == api_key:
                valid = True
                # Сохраняем system_id в state для использования в обработчике
                request.state.system_id = _sys_id
                break

        if not valid:
            logger.warning("Невалидный API-ключ: %s %s", request.method, request.url.path)
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid API key"},
            )

        return await call_next(request)
