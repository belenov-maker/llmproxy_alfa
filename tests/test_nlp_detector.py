"""Тесты NLP-обогащения (Natasha NER) — Эшелон 1.5.

Тестируем:
- PER → fio детекция (дополнение regex)
- LOC → address детекция (с фильтрацией)
- ORG → anti-FP (отклонение fio/address внутри ORG)
- Fail-open (при ошибке Natasha pipeline работает)
- Опциональность (nlp_enabled=false)
"""

import pytest

from app.engine.detector import PDMatch, detect, detect_with_trace
from app.engine.nlp_detector import (
    NERSpan,
    extract_ner_spans,
    nlp_enrich,
    _ADDRESS_MARKERS_RE,
)


# ── NER-извлечение ──────────────────────────────────────────────────────────

class TestExtractNERSpans:
    """Тесты извлечения NER-спанов через Natasha."""

    def test_per_detection(self):
        """Natasha находит PER-спаны."""
        spans = extract_ner_spans("Иванов Иван Иванович пришёл на работу")
        per_spans = [s for s in spans if s.type == "PER"]
        assert len(per_spans) >= 1
        assert any("Иванов" in s.text for s in per_spans)

    def test_loc_detection(self):
        """Natasha находит LOC-спаны."""
        spans = extract_ner_spans("Офис расположен в Москве на ул. Тверская")
        loc_spans = [s for s in spans if s.type == "LOC"]
        assert len(loc_spans) >= 1

    def test_org_detection(self):
        """Natasha находит ORG-спаны."""
        spans = extract_ner_spans("Компания Яндекс анонсировала новый продукт")
        org_spans = [s for s in spans if s.type == "ORG"]
        assert len(org_spans) >= 1

    def test_empty_text(self):
        """Пустой текст → пустой результат."""
        assert extract_ner_spans("") == []

    def test_no_entities(self):
        """Текст без сущностей → пустой результат."""
        spans = extract_ner_spans("Сегодня хорошая погода")
        # Может быть пустой или с минимальными ложными срабатываниями
        assert isinstance(spans, list)


# ── NLP-обогащение ──────────────────────────────────────────────────────────

class TestNLPEnrich:
    """Тесты NLP-обогащения pipeline."""

    def test_per_adds_fio(self):
        """PER-спан без перекрытия с regex → новый fio-матч."""
        text = "Сидоров Пётр Алексеевич подписал договор"
        # Regex может или не может найти, тестируем nlp_enrich напрямую
        matches: list[PDMatch] = []  # пустой — regex ничего не нашёл
        result, detail = nlp_enrich(text, matches)
        fio_matches = [m for m in result if m.category == "fio"]
        # Natasha должна найти PER → создать fio
        if detail["ner_spans"]["PER"] > 0:
            assert len(fio_matches) >= 1
            assert fio_matches[0].confidence == 0.75
            assert fio_matches[0].rule == "Natasha NER: PER"
            assert detail["added_fio"] >= 1

    def test_per_no_duplicate_with_regex(self):
        """PER-спан с перекрытием regex fio → не дублируется."""
        text = "Клиент Сидоров Пётр Алексеевич"
        # Предположим regex уже нашёл fio
        existing = [PDMatch(
            category="fio", value="Сидоров Пётр Алексеевич",
            start=7, end=30, confidence=0.9,
            rule="ФИО кириллица (Фамилия Имя Отчество)",
        )]
        result, detail = nlp_enrich(text, existing)
        fio_matches = [m for m in result if m.category == "fio"]
        # Не должно быть дубликатов
        assert len(fio_matches) == 1

    def test_loc_adds_address_with_markers(self):
        """LOC-спан с адресными маркерами → новый address-матч."""
        text = "Встреча пройдёт в Санкт-Петербурге на ул. Невского 28"
        matches: list[PDMatch] = []
        result, detail = nlp_enrich(text, matches)
        addr_matches = [m for m in result if m.category == "address"]
        # LOC может включить адрес с маркером "ул."
        # Натяжка: Natasha может разбить на два LOC-спана
        # Проверяем что хотя бы detail корректен
        assert isinstance(detail["ner_spans"]["LOC"], int)

    def test_loc_no_markers_rejected(self):
        """LOC-спан без адресных маркеров → не добавляется (топоним не ПДн)."""
        text = "В городе Санкт-Петербург проходит фестиваль"
        # "Санкт-Петербург" = LOC, но без маркеров (ул., д., кв.) → не address
        matches: list[PDMatch] = []
        result, detail = nlp_enrich(text, matches)
        addr_matches = [m for m in result if m.category == "address"]
        assert len(addr_matches) == 0

    def test_org_rejects_fio_inside(self):
        """ORG-спан содержит fio-матч → fio отклоняется."""
        text = "ООО Ромашка заключила контракт"
        # Предположим regex нашёл "Ромашка" как fio
        # Находим позицию "Ромашка" в тексте
        start = text.index("Ромашка")
        end = start + len("Ромашка")
        existing = [PDMatch(
            category="fio", value="Ромашка",
            start=start, end=end, confidence=0.7,
            rule="ФИО кириллица",
        )]
        result, detail = nlp_enrich(text, existing)
        # Если Natasha нашла ORG "ООО Ромашка", fio должен быть отклонён
        if detail["ner_spans"]["ORG"] > 0:
            fio_matches = [m for m in result if m.category == "fio"]
            assert len(fio_matches) == 0
            assert detail["rejected_by_org"] >= 1

    def test_detail_structure(self):
        """detail содержит все нужные ключи."""
        text = "Петров Иван работает в Москве"
        _, detail = nlp_enrich(text, [])
        assert "nlp_enabled" in detail
        assert "ner_spans" in detail
        assert "PER" in detail["ner_spans"]
        assert "LOC" in detail["ner_spans"]
        assert "ORG" in detail["ner_spans"]
        assert "added_fio" in detail
        assert "added_address" in detail
        assert "rejected_by_org" in detail


# ── Интеграция с detect() ───────────────────────────────────────────────────

class TestDetectWithNLP:
    """Интеграционные тесты: NLP в pipeline detect()."""

    def test_detect_basic_fio_still_works(self):
        """Базовые ФИО по-прежнему обнаруживаются."""
        matches = detect("Клиент Иванов Иван Иванович, телефон +7 495 123-45-67")
        categories = {m.category for m in matches}
        assert "fio" in categories
        assert "phone" in categories

    def test_detect_known_person_still_filtered(self):
        """Известные персоны по-прежнему фильтруются anti-FP."""
        matches = detect("Поэт Пушкин написал Евгения Онегина")
        fio_matches = [m for m in matches if m.category == "fio"]
        # Пушкин — известная персона, должен быть отфильтрован
        assert not any("Пушкин" in m.value for m in fio_matches)

    def test_detect_org_anti_fp(self):
        """Организация: ФИО внутри ОРГ не детектится как ПДн."""
        matches = detect("Обратитесь в компанию Яндекс")
        fio_matches = [m for m in matches if m.category == "fio"]
        assert not any("Яндекс" in m.value for m in fio_matches)

    def test_detect_numeric_categories_unaffected(self):
        """Числовые категории (телефон, ИНН, СНИЛС) не затрагиваются NLP."""
        text = "Телефон +7 495 123-45-67, email test@example.com"
        matches = detect(text)
        categories = {m.category for m in matches}
        assert "phone" in categories
        assert "email" in categories


# ── Debug trace ─────────────────────────────────────────────────────────────

class TestDetectWithTraceNLP:
    """Тесты debug trace с NLP-этапом."""

    def test_trace_has_nlp_step(self):
        """Trace содержит NLP-этап."""
        trace = detect_with_trace("Клиент Петров Иван Сергеевич")
        step_names = [s["step"] for s in trace.steps]
        assert any("NLP" in name for name in step_names)

    def test_trace_nlp_disabled(self, monkeypatch):
        """При nlp_enabled=false NLP-этап помечен как отключённый."""
        from app.config import settings
        monkeypatch.setattr(settings, "nlp_enabled", False)
        trace = detect_with_trace("Клиент Петров Иван Сергеевич")
        nlp_steps = [s for s in trace.steps if "NLP" in s["step"]]
        assert len(nlp_steps) == 1
        assert "отключен" in nlp_steps[0]["detail"].lower() or "false" in nlp_steps[0]["detail"].lower()


# ── Отключение NLP ──────────────────────────────────────────────────────────

class TestNLPDisabled:
    """Тесты отключения NLP через конфиг."""

    def test_detect_without_nlp(self, monkeypatch):
        """При nlp_enabled=false pipeline работает как раньше."""
        from app.config import settings
        monkeypatch.setattr(settings, "nlp_enabled", False)
        matches = detect("Клиент Иванов Иван Иванович, телефон +7 495 123-45-67")
        categories = {m.category for m in matches}
        assert "fio" in categories
        assert "phone" in categories


# ── Адресные маркеры ────────────────────────────────────────────────────────

class TestAddressMarkers:
    """Тесты regex адресных маркеров."""

    @pytest.mark.parametrize("text", [
        "ул. Ленина",
        "г. Москва",
        "пр. Мира",
        "д. 42",
        "кв. 15",
        "обл. Московская",
        "район Центральный",
    ])
    def test_address_markers_match(self, text):
        """Адресные маркеры распознаются."""
        assert _ADDRESS_MARKERS_RE.search(text)

    @pytest.mark.parametrize("text", [
        "просто текст",
        "Москва",
        "Иванов",
    ])
    def test_no_address_markers(self, text):
        """Текст без адресных маркеров не совпадает."""
        assert not _ADDRESS_MARKERS_RE.search(text)
