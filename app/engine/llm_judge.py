"""LLM-as-a-judge для классификации ПДн (Эшелон 2).

Используем DeepSeek V4 Flash через AlfaGen для:
1. Подтверждения/отклонения regex-срабатываний (anti-FP)
2. Обнаружения ПДн, пропущенных regex
3. Контекстной классификации

Паттерн: prompt → JSON вердикт → parse (по образцу eval_evaluators.LLMJudge).
Fail-open: при ошибке LLM → принимаем regex-результат как есть.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.engine.detector import PDMatch

logger = logging.getLogger(__name__)

# ───────────────────────────────────────────────────────────────────
# Промпт для LLM-классификатора
# ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Ты — классификатор персональных данных (ПДн) для российского законодательства.

Получаешь текст и предварительные результаты regex-детектора.
Твоя задача:
1. Подтвердить или отклонить каждое regex-срабатывание (anti-FP)
2. Найти ПДн которые regex пропустил
3. Классифицировать каждый фрагмент по категории

Категории ПДн:
- fio: ФИО (Фамилия Имя Отчество)
- birth_date: дата рождения
- birth_place: место рождения
- passport: паспорт (серия + номер)
- citizenship: гражданство
- issuing_authority: орган выдачи документа
- subdivision_code: код подразделения
- issue_date: дата выдачи документа
- drivers_license: водительское удостоверение
- address: адрес (регистрации, проживания)
- email: электронная почта
- phone: номер телефона
- inn: ИНН
- card_number: номер банковской карты
- cvv: CVV/CVC код
- pin: ПИН-код
- cardholder_name: имя держателя карты
- snils: СНИЛС
- oms: полис ОМС
- foreign_passport: загранпаспорт
- military_id: военный билет

Правила anti-FP:
- Известные исторические личности (Пушкин, Толстой, Достоевский) — НЕ ПДн
- Публичные лица в контексте новостей (Президент, министр) — НЕ ПДн
- Названия улиц/организаций, содержащие фамилии (ул. Пушкина) — категория address, не fio
- Даты без контекста рождения — НЕ birth_date
- Числа, похожие на документы, но без контекста — confidence ниже
- «ПИН 1234» без контекста карты — подозрительно, но confidence ниже
- Юридические лица (ООО, АО, ЗАО) — НЕ ПДн

Ответ строго JSON (без markdown fences, без пояснений):
{
  "findings": [
    {
      "text": "найденный фрагмент",
      "category": "fio",
      "is_pii": true,
      "confidence": 0.95,
      "reason": "краткое обоснование"
    }
  ]
}"""


USER_PROMPT_TEMPLATE = """Текст для анализа:
---
{text}
---

Предварительные regex-результаты:
{regex_results}

Проанализируй текст. Для каждого regex-результата: подтверди (is_pii=true) или отклони (is_pii=false) с обоснованием. Найди ПДн, пропущенные regex. Ответ строго JSON."""


@dataclass
class LLMFinding:
    """Результат LLM-классификации одного фрагмента."""
    text: str
    category: str
    is_pii: bool
    confidence: float
    reason: str


@dataclass
class LLMJudgeResult:
    """Полный результат работы LLM-judge."""
    findings: list[LLMFinding]
    llm_latency_ms: float
    raw_response: str
    error: str | None = None


def _parse_verdict(raw: str) -> list[dict[str, Any]]:
    """Парсинг JSON из ответа LLM (по образцу eval_evaluators._parse_verdict).

    Обрабатывает:
    - Чистый JSON
    - JSON в markdown fences ```json...```
    - JSON внутри текста (первый { ... })
    """
    text = raw.strip()

    # Убираем markdown fences
    if "```" in text:
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()

    # Пробуем парсить напрямую
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "findings" in data:
            return data["findings"]
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: ищем первый JSON-объект
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict) and "findings" in data:
                return data["findings"]
        except (json.JSONDecodeError, ValueError):
            pass

    return []


def _format_regex_results(matches: list[PDMatch]) -> str:
    """Форматировать regex-результаты для промпта."""
    if not matches:
        return "Regex не обнаружил ПДн."
    lines = []
    for m in matches:
        lines.append(f"- [{m.category}] \"{m.value}\" (confidence={m.confidence:.2f})")
    return "\n".join(lines)


async def judge(
    text: str,
    regex_matches: list[PDMatch],
    *,
    base_url: str,
    api_key: str,
    model: str = "deepseek-ai/DeepSeek-V4-Flash-0731",
    timeout: float = 10.0,
    max_tokens: int = 4096,
) -> LLMJudgeResult:
    """Вызвать LLM-as-a-judge для валидации regex-результатов.

    Args:
        text: Анализируемый текст.
        regex_matches: Результаты regex-детекции (Эшелон 1).
        base_url: URL AlfaGen API.
        api_key: API ключ.
        model: Модель LLM.
        timeout: Таймаут запроса (сек).
        max_tokens: Максимум токенов в ответе.

    Returns:
        LLMJudgeResult с findings и метриками.
    """
    user_prompt = USER_PROMPT_TEMPLATE.format(
        text=text[:8000],  # Ограничиваем для экономии токенов
        regex_results=_format_regex_results(regex_matches),
    )

    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "stream": False,
    }

    start = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                json=request_body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        logger.warning("LLM-judge ошибка (fail-open): %s", e)
        return LLMJudgeResult(
            findings=[],
            llm_latency_ms=elapsed,
            raw_response="",
            error=str(e),
        )

    elapsed = (time.monotonic() - start) * 1000

    # Извлечь ответ
    try:
        raw_content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        return LLMJudgeResult(
            findings=[],
            llm_latency_ms=elapsed,
            raw_response=json.dumps(data, ensure_ascii=False)[:500],
            error="Не удалось извлечь content из ответа LLM",
        )

    # Парсинг JSON
    raw_findings = _parse_verdict(raw_content)
    findings = []
    for f in raw_findings:
        try:
            findings.append(LLMFinding(
                text=str(f.get("text", "")),
                category=str(f.get("category", "unknown")),
                is_pii=bool(f.get("is_pii", True)),
                confidence=float(f.get("confidence", 0.5)),
                reason=str(f.get("reason", "")),
            ))
        except (TypeError, ValueError):
            continue

    return LLMJudgeResult(
        findings=findings,
        llm_latency_ms=elapsed,
        raw_response=raw_content[:2000],
    )


def merge_results(
    regex_matches: list[PDMatch],
    llm_result: LLMJudgeResult,
) -> list[PDMatch]:
    """Объединить результаты regex и LLM.

    Логика:
    1. Regex-совпадения, отклонённые LLM (is_pii=false) → удаляются
    2. Regex-совпадения, подтверждённые LLM → confidence обновляется
    3. Новые findings от LLM (не найденные regex) → добавляются
    """
    if llm_result.error or not llm_result.findings:
        # Fail-open: если LLM недоступен, возвращаем regex как есть
        return regex_matches

    # Индексируем LLM findings по тексту
    llm_by_text: dict[str, LLMFinding] = {}
    for f in llm_result.findings:
        llm_by_text[f.text.strip()] = f

    # 1. Фильтруем regex-результаты
    filtered: list[PDMatch] = []
    for match in regex_matches:
        llm_finding = llm_by_text.pop(match.value.strip(), None)
        if llm_finding is not None:
            if llm_finding.is_pii:
                # Подтверждено LLM — обновляем confidence
                match.confidence = max(match.confidence, llm_finding.confidence)
                filtered.append(match)
            # else: отклонено LLM — пропускаем (anti-FP)
        else:
            # LLM не высказался — оставляем regex как есть
            filtered.append(match)

    # 2. Добавляем новые findings от LLM (не найденные regex)
    for text, finding in llm_by_text.items():
        if finding.is_pii and finding.confidence >= 0.5:
            filtered.append(PDMatch(
                category=finding.category,
                value=finding.text,
                start=-1,  # Позиция неизвестна — будет найдена при маскировании
                end=-1,
                confidence=finding.confidence,
                rule=f"LLM-judge: {finding.reason}",
            ))

    return sorted(filtered, key=lambda m: m.start if m.start >= 0 else float("inf"))
