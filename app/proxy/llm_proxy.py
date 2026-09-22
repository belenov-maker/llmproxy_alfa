"""LLM-прокси: маскирование → LLM (AlfaGen) → демаскирование.

@business-process Безопасное проксирование запросов к LLM
@business-rule BR-PROXY-01 ПДн никогда не отправляются в LLM — только замаскированный текст.
@business-rule BR-PROXY-02 Ответ LLM демаскируется перед возвратом клиенту.
@business-rule BR-PROXY-03 Timeout на запрос к LLM — 120 секунд (AlfaGen может быть медленным).
@business-rule BR-PROXY-04 Retry: до 2 повторов при 429 / 5xx, exponential backoff.
@integration AlfaGen DeepSeek V4 Flash (OpenAI-совместимый API)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx

from app.config import settings
from app.engine.detector import detect
from app.engine.masker import mask_text, MaskResult
from app.engine.unmasker import unmask_text

logger = logging.getLogger(__name__)

# ─── Настройки ───────────────────────────────────────────────
_LLM_TIMEOUT = 120.0  # AlfaGen может быть медленным
_MAX_RETRIES = 2
_RETRY_BACKOFF = [1.0, 3.0]  # секунды между повторами


@dataclass
class ProxyResult:
    """Результат проксирования через LLM."""

    result: str  # Демаскированный ответ LLM
    masked_input: str  # Маскированный вход (для отладки)
    llm_raw: str  # Сырой ответ LLM (с плейсхолдерами)
    pd_found: int = 0
    categories: list[str] = field(default_factory=list)
    regex_ms: float = 0.0
    jev_ms: float = 0.0
    llm_ms: float = 0.0
    total_ms: float = 0.0
    error: str | None = None


async def _call_llm(
    messages: list[dict[str, str]],
    model: str,
) -> tuple[str, float]:
    """Вызвать LLM API с retry при 429/5xx.

    Returns:
        (response_text, latency_ms)
    """
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 4096,
    }

    last_error: Exception | None = None
    t0 = time.perf_counter()

    async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await client.post(
                    f"{settings.llm_base_url}/chat/completions",
                    headers=headers,
                    json=body,
                )
                if resp.status_code == 429:
                    # Rate-limited — ждём и повторяем
                    if attempt < _MAX_RETRIES:
                        wait = _RETRY_BACKOFF[attempt] if attempt < len(_RETRY_BACKOFF) else 3.0
                        logger.warning("LLM 429: retry %d/%d через %.1fs", attempt + 1, _MAX_RETRIES, wait)
                        await asyncio.sleep(wait)
                        continue
                resp.raise_for_status()
                data = resp.json()
                text = data["choices"][0]["message"]["content"]
                ms = (time.perf_counter() - t0) * 1000
                return text, ms
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code >= 500 and attempt < _MAX_RETRIES:
                    wait = _RETRY_BACKOFF[attempt] if attempt < len(_RETRY_BACKOFF) else 3.0
                    logger.warning("LLM %d: retry %d/%d через %.1fs", e.response.status_code, attempt + 1, _MAX_RETRIES, wait)
                    await asyncio.sleep(wait)
                    continue
                raise
            except Exception as e:
                last_error = e
                if attempt < _MAX_RETRIES:
                    wait = _RETRY_BACKOFF[attempt] if attempt < len(_RETRY_BACKOFF) else 3.0
                    logger.warning("LLM error: retry %d/%d через %.1fs: %s", attempt + 1, _MAX_RETRIES, wait, e)
                    await asyncio.sleep(wait)
                    continue
                raise

    raise last_error or RuntimeError("LLM call failed")


async def proxy_to_llm(
    text: str,
    llm_prompt: str = "",
    system_id: str = "default",
) -> ProxyResult:
    """Замаскировать текст → отправить в LLM → демаскировать ответ.

    Args:
        text: Исходный текст с ПДн.
        llm_prompt: System-промпт для LLM.
        system_id: ID системы-потребителя.

    Returns:
        ProxyResult с демаскированным ответом.
    """
    start = time.perf_counter()

    # ═══ Эшелон 1: Regex-детекция ═══
    t0 = time.perf_counter()
    regex_matches = detect(text)
    regex_ms = (time.perf_counter() - t0) * 1000

    # ═══ Эшелон 2: FastJev (если включён) ═══
    jev_ms = 0.0
    final_matches = regex_matches
    if settings.jev_enabled and regex_matches:
        from app.engine.jev_judge import verify_matches

        t1 = time.perf_counter()
        final_matches, batch = verify_matches(text, regex_matches)
        jev_ms = batch.total_ms if batch.total_ms > 0 else (time.perf_counter() - t1) * 1000

    # ═══ Маскирование ═══
    mask_result = mask_text(text, final_matches)
    categories = list(set(m.category for m in final_matches))

    logger.info(
        "Proxy: замаскировано %d ПДн [%s], masked_len=%d",
        mask_result.pd_count,
        ",".join(categories),
        len(mask_result.masked_text),
    )

    # ═══ Проверка: LLM настроен? ═══
    if not settings.llm_base_url or not settings.llm_api_key:
        total_ms = (time.perf_counter() - start) * 1000
        return ProxyResult(
            result=mask_result.masked_text,
            masked_input=mask_result.masked_text,
            llm_raw="",
            pd_found=mask_result.pd_count,
            categories=categories,
            regex_ms=round(regex_ms, 2),
            jev_ms=round(jev_ms, 2),
            total_ms=round(total_ms, 2),
            error="LLM не настроен (PD_PROXY_LLM_BASE_URL / PD_PROXY_LLM_API_KEY)",
        )

    # ═══ Запрос к LLM ═══
    messages: list[dict[str, str]] = []
    if llm_prompt:
        messages.append({"role": "system", "content": llm_prompt})
    messages.append({"role": "user", "content": mask_result.masked_text})

    llm_response = ""
    llm_ms = 0.0
    error = None
    try:
        llm_response, llm_ms = await _call_llm(messages, settings.llm_model)
    except Exception as e:
        logger.exception("Ошибка LLM-прокси")
        llm_response = ""
        error = str(e)

    # ═══ Демаскирование ответа LLM ═══
    unmasked = unmask_text(llm_response, mask_result.reverse_map) if llm_response else ""

    total_ms = (time.perf_counter() - start) * 1000

    logger.info(
        "Proxy: LLM ответил за %.0fms, total=%.0fms, pd=%d",
        llm_ms,
        total_ms,
        mask_result.pd_count,
    )

    return ProxyResult(
        result=unmasked,
        masked_input=mask_result.masked_text,
        llm_raw=llm_response,
        pd_found=mask_result.pd_count,
        categories=categories,
        regex_ms=round(regex_ms, 2),
        jev_ms=round(jev_ms, 2),
        llm_ms=round(llm_ms, 2),
        total_ms=round(total_ms, 2),
        error=error,
    )
