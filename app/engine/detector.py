"""Детектор ПДн — Эшелон 1 (regex).

Единая точка входа: ``detect(text) → list[PDMatch]``.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.regex_rules import ALL_RULES


# ---------------------------------------------------------------------------
# Anti-FP: стоп-лист для ФИО (известные личности, персонажи, организации)
# ---------------------------------------------------------------------------

# Маркеры «НЕ персональные данные» — окно ±5 слов вокруг ФИО
_NOT_PD_MARKERS = {
    # Титулы / должности публичных лиц
    "президент", "премьер", "министр", "губернатор", "мэр",
    "депутат", "сенатор", "посол", "академик", "профессор",
    "поэт", "писатель", "художник", "композитор", "учёный",
    "ученый", "космонавт", "маршал", "генерал", "адмирал",
    "режиссёр", "режиссер", "актёр", "актер", "скульптор",
    "музыкант", "певец", "певица", "дирижёр", "дирижер",
    "изобретатель", "полководец", "император", "императрица",
    "царь", "царица", "князь", "княгиня", "герой", "героиня",
    "революционер", "философ", "историк", "математик", "физик",
    "химик", "биолог", "архитектор", "лауреат",
    # Организационные формы
    "ооо", "зао", "оао", "пао", "ао", "ип",
    "компания", "организация", "корпорация", "фонд",
}

# Маркеры «точно персональные данные» — усилители (окно ±5 слов)
_PD_MARKERS = {
    "клиент", "клиента", "клиенту", "клиентом",
    "заёмщик", "заемщик", "заёмщика", "заемщика",
    "абонент", "абонента", "абоненту",
    "пассажир", "пассажира", "пассажиру",
    "пациент", "пациента", "пациенту",
    "гражданин", "гражданина", "гражданке",
    "сотрудник", "сотрудника", "сотруднику",
    "работник", "работника", "работнику",
    "заявитель", "заявителя", "заявителю",
    "истец", "истца", "истцу",
    "ответчик", "ответчика", "ответчику",
    "владелец", "владельца", "владельцу",
    "собственник", "собственника",
    "арендатор", "арендатора",
    "получатель", "получателя",
    "отправитель", "отправителя",
}

# Обратная совместимость
_FIO_STOP_PREFIXES = _NOT_PD_MARKERS

# Известные персоны (нормализованные фамилии в нижнем регистре, ~70 персон)
_KNOWN_PERSONS = {
    # Писатели / поэты
    "пушкин", "лермонтов", "толстой", "достоевский", "чехов",
    "гоголь", "тургенев", "есенин", "булгаков", "набоков",
    "маяковский", "ахматова", "цветаева", "блок", "куприн",
    "бунин", "горький", "солженицын", "пастернак",
    "некрасов", "грибоедов", "мережковский", "фет", "тютчев",
    "лесков", "шолохов", "бродский", "мандельштам",
    # Учёные
    "менделеев", "ломоносов", "павлов", "королёв", "королев",
    "сахаров", "курчатов", "циолковский", "вернадский",
    "лобачевский", "ковалевская", "попов", "ландау", "капица",
    "вавилов",
    # Политики / госдеятели
    "путин", "медведев", "ельцин", "горбачёв", "горбачев",
    "ленин", "сталин", "хрущёв", "хрущев", "брежнев",
    "невский", "донской", "кутузов", "суворов", "жуков",
    # Композиторы / музыканты
    "чайковский", "рахманинов", "шостакович", "стравинский",
    "мусоргский", "глинка", "прокофьев", "римский-корсаков",
    # Художники / скульпторы
    "репин", "суриков", "шишкин", "айвазовский", "малевич",
    "кандинский", "шагал", "васнецов",
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

def _inn_check(number: str) -> bool:
    """Проверка контрольной суммы ИНН (ФНС России).

    ИНН-12 (физлицо): проверка 11-й и 12-й цифры.
    ИНН-10 (юрлицо): проверка 10-й цифры.
    """
    digits = [int(d) for d in number if d.isdigit()]
    if len(digits) == 12:
        w11 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        w12 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        c11 = sum(d * w for d, w in zip(digits, w11)) % 11 % 10
        c12 = sum(d * w for d, w in zip(digits, w12)) % 11 % 10
        return digits[10] == c11 and digits[11] == c12
    elif len(digits) == 10:
        w10 = [2, 4, 10, 3, 5, 9, 4, 6, 8]
        c10 = sum(d * w for d, w in zip(digits, w10)) % 11 % 10
        return digits[9] == c10
    return False


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

            # Для ИНН — проверка контрольной суммы (повышает/понижает confidence)
            if rule.category == "inn":
                digits_only = "".join(c for c in value if c.isdigit())
                if _inn_check(digits_only):
                    confidence = min(confidence + 0.1, 1.0)
                elif not rule.context_required:
                    # Без контекста и без валидной контрольной суммы — отбрасываем
                    continue

            raw_matches.append(PDMatch(
                category=rule.category,
                value=value,
                start=start,
                end=end,
                confidence=confidence,
                rule=rule.description,
            ))

    # Фильтрация карт с низким confidence (non-Luhn)
    raw_matches = [m for m in raw_matches
                   if not (m.category == "card_number" and m.confidence < 0.5)]

    # Дедупликация перекрывающихся совпадений
    deduplicated = _deduplicate(raw_matches)

    # Контекстная фильтрация
    deduplicated = _context_filter(deduplicated)

    # Anti-FP: фильтрация ФИО (известные личности, организации, персонажи)
    deduplicated = _fio_anti_fp(text, deduplicated)

    # Сортировка по позиции
    deduplicated.sort(key=lambda m: (m.start, -m.end))
    return deduplicated


_CONTEXT_WINDOW = 5  # ±5 слов вокруг спана (как у AlfaSonar)


def _get_window_words(text: str, start: int, end: int, window: int = _CONTEXT_WINDOW) -> list[str]:
    """Получить слова в окне ±window вокруг спана [start, end)."""
    # Разбиваем текст на слова с позициями
    words_with_pos: list[tuple[str, int, int]] = []
    i = 0
    while i < len(text):
        if text[i].isalpha() or text[i] == '-':
            j = i
            while j < len(text) and (text[j].isalpha() or text[j] == '-'):
                j += 1
            words_with_pos.append((text[i:j].lower(), i, j))
            i = j
        else:
            i += 1

    if not words_with_pos:
        return []

    # Находим индексы слов, пересекающихся со спаном
    lo, hi = len(words_with_pos), -1
    for idx, (_, ws, we) in enumerate(words_with_pos):
        if we > start and ws < end:
            lo = min(lo, idx)
            hi = max(hi, idx)

    if hi == -1:
        return []

    a = max(0, lo - window)
    b = min(len(words_with_pos), hi + 1 + window)
    # Возвращаем слова вне спана (только контекст)
    return [w for w, ws, we in words_with_pos[a:b] if we <= start or ws >= end]


def _fio_anti_fp(text: str, matches: list[PDMatch]) -> list[PDMatch]:
    """Anti-FP фильтрация ФИО: убираем известных людей, персонажей, организации.

    Правила:
    1. ФИО содержит фамилию из стоп-листа известных персон → пропускаем
    2. ФИО содержит фамилию литературного персонажа → пропускаем
    3. ФИО начинается со слова-маркера (ООО, Президент, Компания) → пропускаем
    4. ФИО содержит организационный префикс (ООО/ЗАО/ОАО/ПАО) внутри → пропускаем
    5. Окно ±5 слов: NOT_PD-маркер рядом → пропускаем (даже если фамилия не в стоп-листе)
    6. Окно ±5 слов: PD-маркер рядом → усиливаем confidence
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

        # 1. Проверка на организационный префикс внутри значения
        if _ORG_PREFIX_RE.search(m.value):
            continue

        # 2. Проверка фамилий на стоп-лист известных персон / персонажей
        is_known = False
        for word in words:
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

        # 3. Оконная проверка ±5 слов вокруг ФИО
        ctx_words = _get_window_words(text, m.start, m.end)

        # NOT_PD маркер в контексте → не ПДн
        has_not_pd = any(w in _NOT_PD_MARKERS for w in ctx_words)
        if has_not_pd:
            continue

        # PD маркер в контексте → усиливаем confidence
        has_pd = any(w in _PD_MARKERS for w in ctx_words)
        if has_pd:
            m = PDMatch(
                category=m.category, value=m.value,
                start=m.start, end=m.end,
                confidence=min(m.confidence + 0.1, 1.0),
                rule=m.rule,
            )

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
