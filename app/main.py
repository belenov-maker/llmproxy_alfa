"""PD-Proxy — FastAPI-приложение для маскирования персональных данных.

@business-process Двухэшелонная обработка ПДн
@integration FastJev (llama-cpp-python, Qwen3-0.6B GGUF, CPU)

Архитектура:
- Эшелон 1: regex-детектор (быстрый, <10мс)
- Эшелон 2: FastJev (anti-FP верификация, ~50-200мс на CPU)
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings, load_systems_config
from app.metrics import (
    REQUESTS_TOTAL,
    REQUEST_LATENCY,
    PD_DETECTED,
    JEV_FILTERED,
    STORAGE_SIZE,
    get_metrics,
)
from app.models import (
    AdminSystemConfig,
    HealthResponse,
    ProcessMode,
    ProcessRequest,
    ProcessResponse,
    ProcessStats,
    ProxyRequest,
    ProxyResponse,
    ProxyStats,
)
from app.storage.memory import InMemoryStorage, MaskingEntry
from app.engine.detector import detect
from app.engine.masker import mask_text
from app.engine.unmasker import unmask_text
from app.proxy.llm_proxy import proxy_to_llm
from app.engine.jev_judge import verify_matches

logger = logging.getLogger(__name__)

app = FastAPI(
    title="PD-Proxy",
    description="Модуль безопасности персональных данных (regex + FastJev)",
    version=settings.version,
)

# CORS — разрешаем запросы с UI (может открываться по IP или localhost)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting middleware
from app.security.rate_limit import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware, rate=5000.0, burst=200)

# Auth middleware (условный — включается через PD_PROXY_AUTH_ENABLED=true)
if settings.auth_enabled:
    from app.security.auth import APIKeyMiddleware
    app.add_middleware(APIKeyMiddleware)

# Тестовая консоль (static/index.html)
_static_dir = Path(__file__).resolve().parent.parent / "static"
if _static_dir.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_static_dir), html=True), name="ui")

# Глобальное хранилище маппингов
storage = InMemoryStorage(
    ttl=settings.storage_ttl_seconds,
    max_size=settings.storage_max_size,
)

# Structured logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format='{"time":"%(asctime)s","level":"%(levelname)s","module":"%(name)s","msg":"%(message)s"}',
)


def _hash_payload(payload: Any) -> str:
    """SHA-256 хэш payload для идемпотентности."""
    text = str(payload) if not isinstance(payload, str) else payload
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _extract_text(payload: Any) -> str:
    """Извлечь текст из payload для анализа."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        parts = []
        for v in payload.values():
            parts.append(_extract_text(v))
        return " ".join(parts)
    if isinstance(payload, list):
        return " ".join(_extract_text(item) for item in payload)
    return str(payload)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Health-check endpoint."""
    return HealthResponse(version=settings.version)


@app.get("/metrics")
async def metrics():
    """Prometheus-метрики."""
    STORAGE_SIZE.set(storage.size())
    return PlainTextResponse(
        content=get_metrics().decode("utf-8"),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.post("/process", response_model=ProcessResponse)
async def process(request: ProcessRequest) -> ProcessResponse:
    """Маскирование / демаскирование персональных данных.

    Логика по payload_id:
    1. Новый payload_id → детекция + маскирование → сохранение mapping
    2. Существующий payload_id, другой payload → демаскирование
    3. Существующий payload_id, тот же payload → кэшированный результат
    """
    start_time = time.monotonic()
    payload_hash = _hash_payload(request.payload)
    system_id = request.system_id or "default"

    # Проверяем существующую запись
    existing = storage.get(request.payload_id)

    if existing is not None:
        if existing.payload_hash == payload_hash:
            # Идемпотентный повтор — возвращаем кэшированный результат
            REQUESTS_TOTAL.labels(action="cached", system_id=system_id).inc()
            return ProcessResponse(
                result=existing.masked_result or request.payload,
                payload_id=request.payload_id,
                action="cached",
            )
        else:
            # Тот же payload_id, другой payload → демаскирование
            text = request.payload if isinstance(request.payload, str) else str(request.payload)
            unmasked = unmask_text(text, existing.reverse_map)
            elapsed = (time.monotonic() - start_time) * 1000
            REQUESTS_TOTAL.labels(action="unmasked", system_id=system_id).inc()
            REQUEST_LATENCY.labels(action="unmasked").observe(elapsed / 1000)
            return ProcessResponse(
                result=unmasked,
                payload_id=request.payload_id,
                action="unmasked",
                stats=ProcessStats(total_ms=round(elapsed, 2)),
            )

    # Новый payload_id → маскирование
    # Определяем режим
    systems_config = load_systems_config()
    system_cfg = systems_config.get("systems", {}).get(system_id, {})
    mode = request.mode or ProcessMode(system_cfg.get("mode", "full"))

    # Извлекаем текст для анализа
    text = _extract_text(request.payload)

    # ═══ Эшелон 1: Regex ═══
    regex_start = time.monotonic()
    regex_matches = detect(text)
    regex_ms = (time.monotonic() - regex_start) * 1000

    # ═══ Эшелон 2: FastJev (если mode=full) ═══
    jev_ms = 0.0
    final_matches = regex_matches
    regex_count = len(regex_matches)

    if mode == ProcessMode.FULL and regex_matches:
        jev_start = time.monotonic()
        final_matches, jev_batch = verify_matches(text, regex_matches)
        jev_ms = (time.monotonic() - jev_start) * 1000
        if jev_batch.total_ms > 0:
            jev_ms = jev_batch.total_ms

        # Метрики FastJev
        filtered_count = regex_count - len(final_matches)
        if filtered_count > 0:
            JEV_FILTERED.inc(filtered_count)

    # ═══ Маскирование ═══
    masking_style = system_cfg.get("masking_style", "placeholder")
    mask_result = mask_text(text, final_matches, style=masking_style)

    # Сохраняем маппинг
    entry = MaskingEntry(
        payload_id=request.payload_id,
        forward_map=mask_result.forward_map,
        reverse_map=mask_result.reverse_map,
        payload_hash=payload_hash,
        masked_result=mask_result.masked_text,
    )
    storage.put(entry)

    elapsed = (time.monotonic() - start_time) * 1000
    categories = list(set(m.category for m in final_matches))

    # Метрики
    REQUESTS_TOTAL.labels(action="masked", system_id=system_id).inc()
    REQUEST_LATENCY.labels(action="masked").observe(elapsed / 1000)
    for cat in categories:
        PD_DETECTED.labels(category=cat).inc()

    logger.debug(
        "Обработан payload_id=%s: %d ПДн (%s), regex=%.1fms, jev=%.1fms, total=%.1fms",
        request.payload_id,
        mask_result.pd_count,
        ",".join(categories),
        regex_ms,
        jev_ms,
        elapsed,
    )

    return ProcessResponse(
        result=mask_result.masked_text,
        payload_id=request.payload_id,
        action="masked",
        stats=ProcessStats(
            pd_found=mask_result.pd_count,
            categories=categories,
            regex_ms=round(regex_ms, 2),
            jev_ms=round(jev_ms, 2),
            total_ms=round(elapsed, 2),
        ),
    )


# ═══ LLM Proxy ═══


@app.post("/proxy", response_model=ProxyResponse)
async def proxy(request: ProxyRequest) -> ProxyResponse:
    """LLM-прокси: маскирование → LLM (AlfaGen) → демаскирование.

    ПДн никогда не покидают периметр: в LLM отправляется только маскированный текст.
    Ответ LLM демаскируется перед возвратом клиенту.
    """
    res = await proxy_to_llm(
        text=request.payload,
        llm_prompt=request.llm_prompt,
        system_id=request.system_id,
    )

    REQUESTS_TOTAL.labels(action="proxy", system_id=request.system_id).inc()
    REQUEST_LATENCY.labels(action="proxy").observe(res.total_ms / 1000)
    for cat in res.categories:
        PD_DETECTED.labels(category=cat).inc()

    return ProxyResponse(
        result=res.result,
        payload_id=request.payload_id,
        masked_input=res.masked_input,
        stats=ProxyStats(
            pd_found=res.pd_found,
            categories=res.categories,
            regex_ms=res.regex_ms,
            jev_ms=res.jev_ms,
            llm_ms=res.llm_ms,
            total_ms=res.total_ms,
        ),
        error=res.error,
    )


# ═══ Admin API ═══


@app.get("/admin/systems")
async def get_systems():
    """Получить конфигурацию всех систем."""
    config = load_systems_config()
    systems = config.get("systems", {})
    # Убираем api_key из ответа (безопасность)
    safe = {}
    for sid, cfg in systems.items():
        if isinstance(cfg, dict):
            safe[sid] = {k: v for k, v in cfg.items() if k != "api_key"}
    return {"systems": safe}


@app.get("/admin/systems/{system_id}")
async def get_system(system_id: str):
    """Получить конфигурацию конкретной системы."""
    config = load_systems_config()
    systems = config.get("systems", {})
    if system_id not in systems:
        return {"error": f"System '{system_id}' not found"}, 404
    cfg = systems[system_id]
    if isinstance(cfg, dict):
        cfg = {k: v for k, v in cfg.items() if k != "api_key"}
    return {"system_id": system_id, "config": cfg}


@app.get("/admin/stats")
async def admin_stats():
    """Статистика хранилища и приложения."""
    return {
        "storage_size": storage.size(),
        "version": settings.version,
        "jev_enabled": settings.jev_enabled,
        "jev_model": settings.jev_model,
        "auth_enabled": settings.auth_enabled,
    }


@app.get("/api/changelog")
async def get_changelog():
    """Отдать содержимое CHANGELOG.md для отображения в UI."""
    changelog_path = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
    if not changelog_path.is_file():
        return JSONResponse({"error": "CHANGELOG.md not found"}, status_code=404)
    return PlainTextResponse(changelog_path.read_text(encoding="utf-8"))
