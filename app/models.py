"""Pydantic-модели запросов и ответов API."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ProcessMode(str, Enum):
    """Режим обработки."""
    FULL = "full"    # regex + FastJev (anti-FP)
    FAST = "fast"    # только regex (для нагрузочного теста)


class ProcessRequest(BaseModel):
    """Запрос на маскирование/демаскирование."""

    payload: Any = Field(..., description="Данные для обработки (текст, dict, list)")
    payload_id: str = Field(..., description="Уникальный идентификатор запроса")
    system_id: str = Field(default="default", description="ID системы-потребителя (из systems.yaml)")
    mode: ProcessMode | None = Field(default=None, description="Режим: full/fast. None = из конфига системы")
    debug: bool = Field(default=False, description="Режим отладки: включить debug-трейс в ответ")


class DebugMatchInfo(BaseModel):
    """Отладочная информация по одному найденному ПДн."""

    category: str = Field(description="Категория ПДн")
    value: str = Field(description="Найденный текст")
    start: int = Field(description="Начальная позиция")
    end: int = Field(description="Конечная позиция")
    confidence: float = Field(description="Уверенность 0.0–1.0")
    rule: str = Field(description="Правило детекции")
    masked_as: str = Field(default="", description="Во что замаскировано")
    detector: str = Field(default="regex", description="Кто нашёл: regex")
    jev_verdict: str = Field(default="", description="Вердикт FastJev: confirmed / rejected / skipped")
    jev_probability: float | None = Field(default=None, description="Вероятность FastJev")
    jev_latency_ms: float | None = Field(default=None, description="Время FastJev (ms)")
    validation: str = Field(default="", description="Доп. валидация: luhn_pass / luhn_fail / inn_valid / snils_valid / …")


class DebugPipelineStep(BaseModel):
    """Один шаг pipeline детекции."""

    step: str = Field(description="Название шага")
    count_before: int = Field(description="Матчей на входе")
    count_after: int = Field(description="Матчей на выходе")
    filtered: int = Field(description="Отфильтровано")
    detail: str = Field(default="", description="Детали фильтрации")


class DebugTrace(BaseModel):
    """Полный debug-трейс обработки."""

    mode: str = Field(description="Режим обработки: full / fast")
    masking_style: str = Field(description="Стиль маскирования")
    system_id: str = Field(description="ID системы")
    pipeline: list[DebugPipelineStep] = Field(default_factory=list, description="Шаги pipeline")
    matches: list[DebugMatchInfo] = Field(default_factory=list, description="Детали по каждому ПДн")
    rejected: list[DebugMatchInfo] = Field(default_factory=list, description="Отклонённые матчи (не прошли фильтры)")
    input_length: int = Field(description="Длина входного текста")


class ProcessResponse(BaseModel):
    """Ответ с результатом обработки."""

    result: Any = Field(..., description="Обработанный payload")
    payload_id: str = Field(..., description="ID запроса")
    action: str = Field(default="masked", description="Действие: masked | unmasked | cached")
    stats: ProcessStats | None = Field(default=None, description="Статистика обработки")
    debug_trace: DebugTrace | None = Field(default=None, description="Debug-трейс (только при debug=true)")


class ProcessStats(BaseModel):
    """Статистика обработки одного запроса."""

    pd_found: int = Field(default=0, description="Количество обнаруженных ПДн")
    categories: list[str] = Field(default_factory=list, description="Обнаруженные категории")
    regex_ms: float = Field(default=0.0, description="Время regex-детекции (мс)")
    jev_ms: float = Field(default=0.0, description="Время FastJev-верификации (мс)")
    total_ms: float = Field(default=0.0, description="Общее время обработки (мс)")


# Обновляем forward ref
ProcessResponse.model_rebuild()


class ProxyRequest(BaseModel):
    """Запрос на проксирование через LLM с маскированием."""

    payload: str = Field(..., description="Текст для отправки в LLM")
    payload_id: str = Field(..., description="Уникальный ID")
    system_id: str = Field(default="default")
    llm_prompt: str = Field(default="", description="System-промпт для LLM")


class ProxyStats(BaseModel):
    """Статистика проксирования."""

    pd_found: int = Field(default=0, description="Количество обнаруженных ПДн")
    categories: list[str] = Field(default_factory=list, description="Категории ПДн")
    regex_ms: float = Field(default=0.0, description="Время regex (мс)")
    jev_ms: float = Field(default=0.0, description="Время FastJev (мс)")
    llm_ms: float = Field(default=0.0, description="Время LLM (мс)")
    total_ms: float = Field(default=0.0, description="Общее время (мс)")


class ProxyResponse(BaseModel):
    """Ответ от LLM-прокси с демаскированным результатом."""

    result: str = Field(..., description="Демаскированный ответ LLM")
    payload_id: str = Field(..., description="ID запроса")
    masked_input: str = Field(default="", description="Маскированный вход (для отладки)")
    stats: ProxyStats | None = Field(default=None, description="Статистика")
    error: str | None = Field(default=None, description="Ошибка (если есть)")


class HealthResponse(BaseModel):
    """Ответ health-check."""

    status: str = "ok"
    version: str = ""


class AdminSystemConfig(BaseModel):
    """Конфигурация системы-потребителя (для admin API)."""

    description: str = ""
    mode: ProcessMode = ProcessMode.FULL
    masking_style: str = "placeholder"
    pd_categories: list[str] = Field(default_factory=list)


class SystemConfigUpdate(BaseModel):
    """Обновление конфигурации системы-потребителя."""

    description: str = Field(default="", description="Описание системы")
    mode: ProcessMode = Field(default=ProcessMode.FULL, description="Режим: full/fast")
    masking_style: str = Field(default="placeholder", description="Стиль: placeholder/typed/partial")
    pd_categories: list[str] = Field(default_factory=list, description="Категории ПДн")
    allow_demasking: bool = Field(default=False, description="Разрешить демаскирование")
