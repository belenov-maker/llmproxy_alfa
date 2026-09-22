"""FastJev-судья (Эшелон 2): anti-FP верификация и классификация ПДн.

@business-process Двухэшелонная обработка ПДн
@business-rule BR-JEV-01 Fail-open: при ошибке FastJev — матч
    считается валидным (regex-результат сохраняется).
@business-rule BR-JEV-02 Порог уверенности: матч отклоняется,
    только если probability(false) > confidence_threshold.
@business-rule BR-JEV-03 Batch-обработка: все матчи одного запроса
    оцениваются единым вызовом decide_many.
@integration FastJev (llama-cpp-python, локальная модель GGUF)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastjev import Boolean, FastJev

from ..config import settings

if TYPE_CHECKING:
    from .detector import PDMatch

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Описания категорий для промптов FastJev
# ---------------------------------------------------------------------------

CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "fio": "полное имя физического лица (ФИО)",
    "phone": "номер телефона физического лица",
    "email": "адрес электронной почты физического лица",
    "passport": "серия и номер паспорта гражданина РФ",
    "foreign_passport": "серия и номер загранпаспорта",
    "inn": "ИНН физического лица (12 цифр)",
    "snils": "СНИЛС физического лица",
    "oms": "номер полиса ОМС",
    "card_number": "номер банковской карты",
    "cardholder_name": "имя владельца банковской карты (латиницей)",
    "cvv": "CVV/CVC-код банковской карты",
    "pin": "PIN-код банковской карты",
    "drivers_license": "номер водительского удостоверения",
    "military_id": "номер военного билета",
    "address": "адрес регистрации или проживания физического лица",
    "birth_date": "дата рождения физического лица",
    "birth_place": "место рождения физического лица",
    "citizenship": "гражданство физического лица",
    "issue_date": "дата выдачи документа, удостоверяющего личность",
    "issuing_authority": "орган, выдавший документ",
    "subdivision_code": "код подразделения в паспорте",
}


# ---------------------------------------------------------------------------
# Результат верификации
# ---------------------------------------------------------------------------


@dataclass
class JevVerdict:
    """Результат проверки одного матча FastJev-судьёй."""

    is_pd: bool
    probability: float  # вероятность того, что это ПДн
    latency_ms: float
    error: str | None = None


@dataclass
class JevBatchResult:
    """Результат пакетной верификации."""

    verdicts: dict[str, JevVerdict] = field(default_factory=dict)
    total_ms: float = 0.0


# ---------------------------------------------------------------------------
# Singleton-экземпляр FastJev
# ---------------------------------------------------------------------------

_jev_instance: FastJev | None = None


def _get_jev() -> FastJev:
    """Lazy-singleton: инициализирует FastJev при первом вызове."""
    global _jev_instance  # noqa: PLW0603
    if _jev_instance is None:
        logger.info(
            "Инициализация FastJev: model=%s, revision=%s",
            settings.jev_model,
            settings.jev_revision,
        )
        t0 = time.perf_counter()
        _jev_instance = FastJev.from_pretrained(
            model=settings.jev_model,
            revision=settings.jev_revision,
            max_input_tokens=settings.jev_max_input_tokens,
        )
        dt = (time.perf_counter() - t0) * 1000
        logger.info("FastJev инициализирован за %.0f ms", dt)
    return _jev_instance


def reset_jev() -> None:
    """Сброс singleton (для тестов)."""
    global _jev_instance  # noqa: PLW0603
    _jev_instance = None


# ---------------------------------------------------------------------------
# Основной API
# ---------------------------------------------------------------------------


def _make_question(match: PDMatch, context: str) -> Boolean:
    """Формирует Boolean-вопрос для одного матча."""
    cat_desc = CATEGORY_DESCRIPTIONS.get(match.category, match.category)

    # Окно контекста: ±80 символов вокруг матча
    ctx_start = max(0, match.start - 80)
    ctx_end = min(len(context), match.end + 80)
    snippet = context[ctx_start:ctx_end]

    instruction = (
        f'В тексте найдено значение "{match.value}". '
        f"Контекст: «{snippet}». "
        f"Это действительно {cat_desc}, относящееся к конкретному "
        f"физическому лицу? Отвечай false, если это вымышленное имя, "
        f"название организации, литературный персонаж, тестовые данные "
        f"или общеизвестный факт."
    )
    return Boolean(
        instruction=instruction,
        true_description=f"Да, это реальные ПДн категории «{cat_desc}».",
        false_description="Нет, это не персональные данные конкретного лица.",
    )


def verify_matches(
    text: str,
    matches: list[PDMatch],
) -> tuple[list[PDMatch], JevBatchResult]:
    """Верифицирует список матчей через FastJev.

    Returns:
        (confirmed_matches, batch_result) — подтверждённые матчи и метрики.
    """
    if not settings.jev_enabled or not matches:
        # Fail-open: если JEV выключен, все матчи проходят
        return matches, JevBatchResult()

    # Формируем вопросы для decide_many
    questions: dict[str, Boolean] = {}
    match_keys: dict[str, PDMatch] = {}
    for i, m in enumerate(matches):
        key = f"m{i}"
        questions[key] = _make_question(m, text)
        match_keys[key] = m

    t0 = time.perf_counter()
    batch_result = JevBatchResult()

    try:
        jev = _get_jev()
        # state — входной контекст для модели (весь текст)
        decisions = jev.decide_many(state=text, questions=questions)
        total_ms = (time.perf_counter() - t0) * 1000
        batch_result.total_ms = total_ms
    except Exception:
        # BR-JEV-01: fail-open — при ошибке сохраняем все матчи
        logger.exception("FastJev ошибка, fail-open: все матчи сохранены")
        total_ms = (time.perf_counter() - t0) * 1000
        batch_result.total_ms = total_ms
        for key, m in match_keys.items():
            batch_result.verdicts[key] = JevVerdict(
                is_pd=True, probability=1.0, latency_ms=total_ms, error="jev_error",
            )
        return matches, batch_result

    # Обработка решений
    confirmed: list[PDMatch] = []
    threshold = settings.jev_confidence_threshold

    for key, m in match_keys.items():
        decision = decisions.get(key)
        if decision is None:
            # Нет решения — fail-open
            batch_result.verdicts[key] = JevVerdict(
                is_pd=True, probability=1.0, latency_ms=total_ms, error="no_decision",
            )
            confirmed.append(m)
            continue

        # decision.probabilities: {True: p_true, False: p_false}
        p_true = decision.probabilities.get(True, 0.5)
        p_false = decision.probabilities.get(False, 0.5)

        # BR-JEV-02: отклоняем только при высокой уверенности, что это НЕ ПДн
        is_pd = p_false <= threshold
        batch_result.verdicts[key] = JevVerdict(
            is_pd=is_pd, probability=p_true, latency_ms=total_ms,
        )

        if is_pd:
            confirmed.append(m)
        else:
            logger.info(
                "JEV отклонил: category=%s, value=%s, p_true=%.3f, p_false=%.3f",
                m.category,
                m.value[:20],
                p_true,
                p_false,
            )

    return confirmed, batch_result
