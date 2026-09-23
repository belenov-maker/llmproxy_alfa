"""Конфигурация структурного JSON-логирования.

@business-process Аудит и трассировка операций
@business-rule BR-LOG-01 Все логи — валидный JSON (корректное экранирование спецсимволов).
@business-rule BR-LOG-02 Каждая запись содержит request_id для сквозной трассировки.
@business-rule BR-LOG-03 Файловый лог опционален (через PD_PROXY_LOG_FILE), с ротацией по размеру.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from pythonjsonlogger.json import JsonFormatter

from app.context import request_id_var


class _RequestIdFilter(logging.Filter):
    """Добавляет request_id из ContextVar в каждую лог-запись."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("-")  # type: ignore[attr-defined]
        return True


# Поля JSON-лога (порядок сохраняется)
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(request_id)s %(message)s"


def setup_logging(
    level: str = "INFO",
    log_file: str = "",
    log_file_max_mb: int = 50,
    log_file_backup_count: int = 5,
) -> None:
    """Настроить корневой логгер с JSON-форматтером.

    Args:
        level: Уровень логирования (DEBUG/INFO/WARNING/ERROR).
        log_file: Путь к файлу логов. Пустая строка — только stdout.
        log_file_max_mb: Максимальный размер файла логов (МБ) до ротации.
        log_file_backup_count: Количество ротируемых файлов.
    """
    root = logging.getLogger()
    log_level = getattr(logging, level.upper(), logging.INFO)
    root.setLevel(log_level)

    # Убираем старые обработчики (от basicConfig и т.п.)
    root.handlers.clear()

    formatter = JsonFormatter(
        fmt=_LOG_FORMAT,
        rename_fields={"asctime": "time", "levelname": "level", "name": "module"},
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    req_filter = _RequestIdFilter()

    # 1. Stdout (всегда)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.addFilter(req_filter)
    root.addHandler(console)

    # 2. Файл (опционально)
    if log_file:
        file_handler = RotatingFileHandler(
            filename=log_file,
            maxBytes=log_file_max_mb * 1024 * 1024,
            backupCount=log_file_backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(req_filter)
        root.addHandler(file_handler)

    # Приглушаем шумные библиотеки
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
