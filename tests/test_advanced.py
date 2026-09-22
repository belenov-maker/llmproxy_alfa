"""Тесты расширенных сценариев: partial masking + контекстное маскирование."""

from __future__ import annotations

import pytest

from app.engine.detector import PDMatch, detect
from app.engine.masker import mask_text, _partial_mask


# ─── Partial masking: unit-тесты _partial_mask ──────────────────


class TestPartialMask:
    """Тесты частичного маскирования."""

    def test_fio_partial(self):
        """ФИО: первый + * + последний символ."""
        result = _partial_mask("Иванов", "fio")
        assert result[0] == "И"
        assert result[-1] == "в"
        assert "*" in result
        assert len(result) == len("Иванов")

    def test_phone_partial(self):
        """Телефон: код страны+оператора + *** + последние 2 цифры."""
        result = _partial_mask("+7 (916) 123-45-67", "phone")
        # Первые 4 цифры (7916) видны, последние 2 (67) видны
        assert "7" in result[:5]  # Код страны
        assert result.endswith("67")
        assert "*" in result

    def test_email_partial(self):
        """Email: первая буква + * + @domain."""
        result = _partial_mask("test@example.com", "email")
        assert result.startswith("t")
        assert "@example.com" in result
        assert "***" in result

    def test_card_partial(self):
        """Карта: первые 4 + * + последние 4."""
        result = _partial_mask("4276 1234 5678 9012", "card_number")
        assert result.startswith("4276")
        assert result.endswith("9012")
        assert "*" in result

    def test_passport_partial(self):
        """Паспорт: первые 2 + * + последние 2 цифры."""
        result = _partial_mask("4510 123456", "passport")
        # Цифры: 4 5 1 0 1 2 3 4 5 6
        # Первые 2 (4, 5) видны, последние 2 (5, 6) видны
        assert result[0] == "4"
        assert result[1] == "5"
        assert "*" in result

    def test_inn_partial(self):
        """ИНН: первые 2 + * + последние 2."""
        result = _partial_mask("770912345678", "inn")
        assert result[:2] == "77"
        assert result[-2:] == "78"
        assert "*" in result

    def test_cvv_full_mask(self):
        """CVV: полностью маскируется."""
        assert _partial_mask("123", "cvv") == "***"

    def test_pin_full_mask(self):
        """PIN: полностью маскируется."""
        assert _partial_mask("1234", "pin") == "****"

    def test_short_value(self):
        """Короткие значения (≤2 символов)."""
        assert _partial_mask("AB", "fio") == "**"
        assert _partial_mask("A", "fio") == "*"

    def test_empty_value(self):
        """Пустое значение."""
        assert _partial_mask("", "fio") == ""

    def test_address_partial(self):
        """Адрес: первый + * + последний."""
        result = _partial_mask("г. Москва, ул. Ленина", "address")
        assert result[0] == "г"
        assert result[-1] == "а"
        assert "*" in result


# ─── mask_text с style=partial ──────────────────────────────────


class TestMaskTextPartial:
    """Тесты mask_text с partial стилем."""

    def test_partial_style_basic(self):
        """Базовый тест partial маскирования."""
        matches = [
            PDMatch(category="fio", value="Иванов", start=0, end=6, confidence=0.9, rule="fio"),
        ]
        result = mask_text("Иванов пришёл", matches, style="partial")
        assert result.masked_text[0] == "И"
        assert "*" in result.masked_text
        assert "пришёл" in result.masked_text
        assert result.pd_count == 1

    def test_partial_phone(self):
        """Partial: телефон маскируется частично."""
        text = "Звоните: +7 (916) 123-45-67"
        matches = detect(text)
        phone_matches = [m for m in matches if m.category == "phone"]
        if phone_matches:
            result = mask_text(text, phone_matches, style="partial")
            assert "67" in result.masked_text  # Последние 2 цифры видны
            assert "*" in result.masked_text

    def test_placeholder_style_unchanged(self):
        """Стиль placeholder не изменился."""
        matches = [
            PDMatch(category="fio", value="Иванов", start=0, end=6, confidence=0.9, rule="fio"),
        ]
        result = mask_text("Иванов пришёл", matches, style="placeholder")
        assert "[FIO_1]" in result.masked_text

    def test_partial_with_reverse_map(self):
        """Partial: reverse_map содержит оригинал."""
        matches = [
            PDMatch(category="email", value="test@mail.ru", start=7, end=19, confidence=0.9, rule="email"),
        ]
        result = mask_text("Почта: test@mail.ru", matches, style="partial")
        # reverse_map: masked_value → original
        assert "test@mail.ru" in result.reverse_map.values()

    def test_partial_deduplication(self):
        """Partial: одинаковые значения маскируются одинаково."""
        matches = [
            PDMatch(category="fio", value="Иванов", start=0, end=6, confidence=0.9, rule="fio"),
            PDMatch(category="fio", value="Иванов", start=20, end=26, confidence=0.9, rule="fio"),
        ]
        text = "Иванов и потом ещё Иванов тут"
        result = mask_text(text, matches, style="partial")
        # Обе замены одинаковы
        masked_val = result.forward_map["Иванов"]
        assert result.masked_text.count(masked_val) == 2


# ─── Контекстная фильтрация ────────────────────────────────────


class TestContextFilter:
    """Тесты контекстного маскирования."""

    def test_pin_without_card_not_detected(self):
        """ПИН без контекста карты НЕ маскируется."""
        # Текст с PIN-кодом, но без номера карты
        text = "Введите ПИН-код: 1234 для входа в систему"
        matches = detect(text)
        pin_matches = [m for m in matches if m.category == "pin"]
        assert len(pin_matches) == 0, f"PIN без карты не должен маскироваться: {pin_matches}"

    def test_pin_with_card_detected(self):
        """ПИН с контекстом карты маскируется."""
        text = "Карта 4276 1234 5678 9012, ПИН-код: 5678"
        matches = detect(text)
        categories = {m.category for m in matches}
        # Карта есть → PIN должен быть
        if "card_number" in categories:
            assert "pin" in categories, "PIN при наличии карты должен маскироваться"

    def test_cvv_without_card_not_detected(self):
        """CVV без контекста карты НЕ маскируется."""
        text = "Код верификации: CVV 123"
        matches = detect(text)
        cvv_matches = [m for m in matches if m.category == "cvv"]
        # CVV без карты — не маскируется (или может не детектиться regex-ом)
        # Если regex нашёл — контекстная фильтрация должна убрать
        assert len(cvv_matches) == 0, f"CVV без карты не должен маскироваться: {cvv_matches}"

    def test_other_categories_unaffected(self):
        """Другие категории не затрагиваются контекстной фильтрацией."""
        text = "Паспорт 4510 123456, ИНН 770912345678"
        matches = detect(text)
        categories = {m.category for m in matches}
        assert "passport" in categories or "inn" in categories
