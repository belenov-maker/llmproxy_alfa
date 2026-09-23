"""Контекстные переменные запроса.

@business-process Трассировка запросов через request_id

Хранит request_id (UUID4) в ContextVar — доступен из любого модуля
без явной передачи через параметры функций.
"""

from __future__ import annotations

from contextvars import ContextVar

# UUID4-идентификатор текущего HTTP-запроса.
# Устанавливается в RequestLoggerMiddleware, читается в логгере.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
