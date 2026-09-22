"""Детектор ПДн — Эшелон 1 (regex).

Единая точка входа: ``detect(text) → list[PDMatch]``.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.regex_rules import ALL_RULES


# ---------------------------------------------------------------------------
# Anti-FP: стоп-лист для ФИО (известные личности, персонажи, организации)
# ---------------------------------------------------------------------------

# Слова-маркеры, указывающие что это не персональные данные
_FIO_STOP_PREFIXES = {
    # Должности / титулы публичных лиц
    "президент", "премьер", "министр", "губернатор", "мэр",
    "депутат", "сенатор", "посол", "академик", "профессор",
    # Организационные формы
    "ооо", "зао", "оао", "пао", "ао", "ип",
    "компания", "организация", "корпорация", "фонд",
}

# Известные персоны (нормализованные фамилии в нижнем регистре)
_KNOWN_PERSONS = {
    # Писатели / поэты
    "пушкин", "лермонтов", "толстой", "достоевский", "чехов",
    "гоголь", "тургенев", "есенин", "булгаков", "набоков",
    "маяковский", "ахматова", "цветаева", "блок", "куприн",
    "бунин", "горький", "солженицын", "пастернак",
    # Учёные
    "менделеев", "ломоносов", "павлов", "королёв", "сахаров",
    "курчатов", "циолковский", "вернадский",
    # Политики / госдеятели
    "путин", "медведев", "ельцин", "горбачёв", "ленин",
    "сталин", "хрущёв", "брежнев",
    # Композиторы / музыканты
    "чайковский", "рахманинов", "шостакович",
    # Художники
    "репин", "суриков", "шишкин", "айвазовский", "малевич",
    "кандинский",
    # Космонавты
    "гагарин", "терешкова",
}

# Литературные персонажи
_FICTION_NAMES = {
    "онегин", "болконский", "безухов", "каренин",
    "раскольников", "мышкин", "обломов", "чичиков",
    "печорин", "базаров", "воланд",
}

import re as _re
_ORG_PREFIX_RE = _re.compile(
    r"\b(?:ООО|ЗАО|ОАО|ПАО|АО|ИП|НКО|ФГУП|МУП|ГБУ|ГУП)\s",
    _re.IGNORECASE,
)


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
            g = rule.use_group if hasattr(rule, 'use_group') else 0
            try:
                value = m.group(g)
                start = m.start(g)
                end = m.end(g)
            except IndexError:
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

    # Anti-FP: фильтрация ФИО (известные личности, организации, персонажи)
    deduplicated = _fio_anti_fp(text, deduplicated)

    # Сортировка по позиции
    deduplicated.sort(key=lambda m: (m.start, -m.end))
    return deduplicated


def _fio_anti_fp(text: str, matches: list[PDMatch]) -> list[PDMatch]:
    """Anti-FP фильтрация ФИО: убираем известных людей, персонажей, организации.

    Правила:
    1. ФИО содержит фамилию из стоп-листа известных персон → пропускаем
    2. ФИО содержит фамилию литературного персонажа → пропускаем
    3. ФИО начинается со слова-маркера (ООО, Президент, Компания) → пропускаем
    4. ФИО содержит организационный префикс (ООО/ЗАО/ОАО/ПАО) внутри → пропускаем
    """
    if not matches:
        return matches

    result = []
    for m in matches:
        if m.category != "fio":
            result.append(m)
            continue

        value_lower = m.value.lower()
        words = value_lower.split()

        # 1a. Проверка на стоп-префиксы (первое слово match)
        if words and words[0] in _FIO_STOP_PREFIXES:
            continue

        # 1b. Проверка слова ПЕРЕД match в тексте (для "Presidente Putin" → ФИО="Putin")
        prefix_text = text[:m.start].rstrip().lower()
        if prefix_text:
            prefix_words = prefix_text.split()
            if prefix_words and prefix_words[-1] in _FIO_STOP_PREFIXES:
                continue

        # 2. Проверка на организационный префикс внутри значения
        if _ORG_PREFIX_RE.search(m.value):
            continue

        # 3. Проверка фамилий на стоп-лист известных персон / персонажей
        is_known = False
        for word in words:
            # Нормализуем: убираем окончания падежей (упрощённо)
            base = word.rstrip("аоуыиеяю")
            for known in _KNOWN_PERSONS | _FICTION_NAMES:
                known_base = known.rstrip("аоуыиеяю")
                if base == known_base or word == known:
                    is_known = True
                    break
            if is_known:
                break

        if is_known:
            continue

        result.append(m)

    return result


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
    1. Выше context_required (контекстное совпадение точнее generic)
    2. Выше priority
    3. При равном priority — более длинное совпадение
    """
    if not matches:
        return []

    # Строим маппинги из ALL_RULES
    rule_priority: dict[str, int] = {}
    rule_ctx: dict[str, bool] = {}
    for r in ALL_RULES:
        rule_priority[r.description] = r.priority
        rule_ctx[r.description] = r.context_required

    # Сортируем: context_required первым, потом высший priority, потом длиннее
    ranked = sorted(
        matches,
        key=lambda m: (
            -(1 if rule_ctx.get(m.rule, False) else 0),
            -rule_priority.get(m.rule, 50),
            -(m.end - m.start),
        ),
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
