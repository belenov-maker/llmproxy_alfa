"""Тесты маскирования и демаскирования."""

import pytest

from app.engine.detector import PDMatch
from app.engine.masker import mask_text, MaskResult
from app.engine.unmasker import unmask_text


# ─── Помощники ────────────────────────────────────────────────────

def _match(cat: str, value: str, start: int, end: int, conf: float = 0.9) -> PDMatch:
    return PDMatch(category=cat, value=value, start=start, end=end, confidence=conf, rule="test")


# ─── mask_text ────────────────────────────────────────────────────

class TestMaskText:
    def test_no_matches(self):
        """Без совпадений текст возвращается без изменений."""
        result = mask_text("Привет мир", [])
        assert result.masked_text == "Привет мир"
        assert result.pd_count == 0
        assert result.forward_map == {}

    def test_single_fio(self):
        """Маскирование одного ФИО."""
        text = "Клиент Иванов Иван Иванович обратился"
        matches = [_match("fio", "Иванов Иван Иванович", 7, 27)]
        result = mask_text(text, matches)
        assert "[FIO_1]" in result.masked_text
        assert "Иванов" not in result.masked_text
        assert result.pd_count == 1
        assert result.forward_map["Иванов Иван Иванович"] == "[FIO_1]"
        assert result.reverse_map["[FIO_1]"] == "Иванов Иван Иванович"

    def test_multiple_categories(self):
        """Маскирование нескольких категорий."""
        text = "Иванов Иван, тел +79161234567, паспорт 4509 123456"
        matches = [
            _match("fio", "Иванов Иван", 0, 11),
            _match("phone", "+79161234567", 17, 29),
            _match("passport", "4509 123456", 40, 51),
        ]
        result = mask_text(text, matches)
        assert "[FIO_1]" in result.masked_text
        assert "[PHONE_1]" in result.masked_text
        assert "[PASSPORT_1]" in result.masked_text
        assert "Иванов" not in result.masked_text
        assert "+7916" not in result.masked_text

    def test_duplicate_values(self):
        """Одинаковые значения получают одинаковый placeholder."""
        text = "Иванов Иван подписал. Иванов Иван утвердил."
        matches = [
            _match("fio", "Иванов Иван", 0, 11),
            _match("fio", "Иванов Иван", 22, 33),
        ]
        result = mask_text(text, matches)
        # Оба вхождения — один placeholder
        assert result.masked_text.count("[FIO_1]") == 2
        assert len(result.forward_map) == 1

    def test_adjacent_matches(self):
        """Смежные совпадения не пересекаются."""
        text = "email: test@mail.ru тел: +79161234567"
        matches = [
            _match("email", "test@mail.ru", 7, 19),
            _match("phone", "+79161234567", 25, 37),
        ]
        result = mask_text(text, matches)
        assert "[EMAIL_1]" in result.masked_text
        assert "[PHONE_1]" in result.masked_text

    def test_empty_text(self):
        """Пустой текст."""
        result = mask_text("", [])
        assert result.masked_text == ""
        assert result.pd_count == 0


# ─── unmask_text ──────────────────────────────────────────────────

class TestUnmaskText:
    def test_basic_unmask(self):
        """Базовое демаскирование."""
        masked = "Клиент [FIO_1] обратился, тел [PHONE_1]"
        reverse_map = {
            "[FIO_1]": "Иванов Иван Иванович",
            "[PHONE_1]": "+79161234567",
        }
        result = unmask_text(masked, reverse_map)
        assert result == "Клиент Иванов Иван Иванович обратился, тел +79161234567"

    def test_roundtrip(self):
        """mask → unmask = исходный текст (roundtrip)."""
        original = "Клиент Иванов Иван, паспорт 4509 123456, тел +79161234567"
        matches = [
            _match("fio", "Иванов Иван", 7, 18),
            _match("passport", "4509 123456", 28, 39),
            _match("phone", "+79161234567", 45, 57),
        ]
        mask_result = mask_text(original, matches)
        restored = unmask_text(mask_result.masked_text, mask_result.reverse_map)
        assert restored == original

    def test_empty_reverse_map(self):
        """Пустой маппинг — текст без изменений."""
        text = "Текст без плейсхолдеров"
        assert unmask_text(text, {}) == text

    def test_unknown_placeholder(self):
        """Неизвестный placeholder остаётся как есть."""
        text = "Клиент [FIO_99] неизвестен"
        result = unmask_text(text, {"[FIO_1]": "Иванов"})
        assert "[FIO_99]" in result

    def test_multiple_same_placeholder(self):
        """Несколько одинаковых плейсхолдеров."""
        text = "[FIO_1] подписал, а [FIO_1] утвердил"
        reverse_map = {"[FIO_1]": "Петров Пётр"}
        result = unmask_text(text, reverse_map)
        assert result == "Петров Пётр подписал, а Петров Пётр утвердил"


# ─── Roundtrip с разными типами ──────────────────────────────────

class TestRoundtrip:
    """Тесты на полный цикл mask → unmask для разных сценариев."""

    def test_all_categories(self):
        """Все основные категории маскируются и демаскируются."""
        text = (
            "ФИО: Сидоров Алексей Петрович, "
            "email: sidorov@mail.ru, "
            "ИНН: 770102345678, "
            "СНИЛС: 123-456-789 00"
        )
        matches = [
            _match("fio", "Сидоров Алексей Петрович", 5, 29),
            _match("email", "sidorov@mail.ru", 38, 53),
            _match("inn", "770102345678", 60, 72),
            _match("snils", "123-456-789 00", 81, 95),
        ]
        mask_result = mask_text(text, matches)
        restored = unmask_text(mask_result.masked_text, mask_result.reverse_map)
        assert restored == text

    def test_unicode_roundtrip(self):
        """Unicode (ё) сохраняется при roundtrip."""
        text = "Клиент Алёхин Артём"
        matches = [_match("fio", "Алёхин Артём", 7, 19)]
        mask_result = mask_text(text, matches)
        restored = unmask_text(mask_result.masked_text, mask_result.reverse_map)
        assert restored == text
        assert "Алёхин" in restored
