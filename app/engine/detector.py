"""Детектор ПДн — Эшелон 1 (regex).

Единая точка входа: ``detect(text) → list[PDMatch]``.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.regex_rules import ALL_RULES


# ---------------------------------------------------------------------------
# Модель результата
# ---------------------------------------------------------------------------

@dataclass
class PDMatch:
    """Результат обнаружения ПДн."""

    category: str      # Категория (fio, passport, phone, …)
    value: str         # Найденный текст
    start: int         # Начальная позиция в тексте
    end: int           # Конечная позиция
    confidence: float  # Уверенность 0.0–1.0
    rule: str          # Описание правила


# ---------------------------------------------------------------------------
# Luhn-алгоритм
# ---------------------------------------------------------------------------

def _luhn_check(number: str) -> bool:
    """Проверка контрольной суммы Luhn для номера карты."""
    digits = [int(d) for d in number if d.isdigit()]
    if len(digits) != 16:
        return False
    # Алгоритм Luhn: удваиваем каждую вторую цифру справа
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ---------------------------------------------------------------------------
# Основная функция детекции
# ---------------------------------------------------------------------------

def detect(text: str) -> list[PDMatch]:
    """Обнаружить все ПДн в тексте (Эшелон 1: regex).

    1. Применить все правила из ``ALL_RULES``
    2. Для ``card_number`` — валидация Luhn (при провале confidence → 0.3)
    3. Дедупликация перекрывающихся совпадений
    4. Сортировка по позиции
    """
    if not text or not text.strip():
        return []

    raw_matches: list[PDMatch] = []

    for rule in ALL_RULES:
        for m in rule.pattern.finditer(text):
            value = m.group(0)
            start = m.start()
            end = m.end()

            # Базовый confidence
            confidence = 0.9 if rule.context_required else 0.7

            # Для карт — Luhn-валидация
            if rule.category == "card_number":
                digits_only = value.replace(" ", "").replace("-", "")
                if _luhn_check(digits_only):
                    confidence = 1.0
                else:
                    confidence = 0.3

            raw_matches.append(PDMatch(
                category=rule.category,
                value=value,
                start=start,
                end=end,
                confidence=confidence,
                rule=rule.description,
            ))

    # Дедупликация перекрывающихся совпадений
    deduplicated = _deduplicate(raw_matches)

    # Контекстная фильтрация
    deduplicated = _context_filter(deduplicated)

    # Сортировка по позиции
    deduplicated.sort(key=lambda m: (m.start, -m.end))
    return deduplicated


def _context_filter(matches: list[PDMatch]) -> list[PDMatch]:
    """Контекстная фильтрация: убираем матчи без нужного контекста.

    Правила:
    - PIN без контекста банковской карты (card_number, cvv, cardholder_name) — не маскируется
    - CVV без контекста карты — не маскируется
    """
    if not matches:
        return matches

    categories_present = {m.category for m in matches}
    card_context = categories_present & {"card_number", "cardholder_name"}

    result = []
    for m in matches:
        if m.category == "pin" and not card_context:
            # ПИН без контекста карты — пропускаем
            continue
        if m.category == "cvv" and not card_context:
            # CVV без контекста карты — пропускаем
            continue
        result.append(m)

    return result


def _deduplicate(matches: list[PDMatch]) -> list[PDMatch]:
    """Убрать перекрывающиеся совпадения.

    Если два совпадения перекрываются (диапазоны ``[start, end)``
    пересекаются) — оставляем то, у которого:
    1. Выше priority (через маппинг category → rule → priority)
    2. При равном priority — более длинное совпадение
    """
    if not matches:
        return []

    # Строим маппинг описание → priority из ALL_RULES
    rule_priority: dict[str, int] = {}
    for r in ALL_RULES:
        rule_priority[r.description] = r.priority

    # Сортируем: высший priority первым, потом длиннее
    ranked = sorted(
        matches,
        key=lambda m: (-rule_priority.get(m.rule, 50), -(m.end - m.start)),
    )

    result: list[PDMatch] = []
    for candidate in ranked:
        overlaps = False
        for accepted in result:
            # Пересечение интервалов [start, end)
            if candidate.start < accepted.end and candidate.end > accepted.start:
                overlaps = True
                break
        if not overlaps:
            result.append(candidate)

    return result
