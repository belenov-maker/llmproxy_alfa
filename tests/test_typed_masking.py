"""Тесты типизированного маскирования (style=typed).

Проверяет формат [ЛЕЙБЛ:маска] для всех категорий ПДн,
а также демаскирование typed-масок через unmasker.
"""

import pytest
from app.engine.detector import detect, PDMatch
from app.engine.masker import mask_text, _typed_mask
from app.engine.unmasker import unmask_text


# ─── _typed_mask() unit tests ───


class TestTypedMaskFIO:
    def test_full_name(self):
        assert _typed_mask("Иванов Иван Иванович", "fio") == "И. И. И."

    def test_two_words(self):
        assert _typed_mask("Петрова Мария", "fio") == "П. М."

    def test_single_name(self):
        assert _typed_mask("Сидоров", "fio") == "С."

    def test_with_initials(self):
        result = _typed_mask("Козлов Д А", "fio")
        assert result == "К. Д. А."


class TestTypedMaskPhone:
    def test_plus7(self):
        result = _typed_mask("+7 (916) 123-45-67", "phone")
        # Первые 2 цифры (7,9) видны, последние 2 (6,7) видны, остальные *
        assert "+" in result
        assert result.count("*") >= 5

    def test_8_format(self):
        result = _typed_mask("89991234567", "phone")
        assert result[0] == "8"
        assert result[-1] == "7"
        assert result[-2] == "6"
        assert "*" in result


class TestTypedMaskEmail:
    def test_basic(self):
        result = _typed_mask("test@example.com", "email")
        assert result == "t***@***.com"

    def test_short_local(self):
        result = _typed_mask("a@mail.ru", "email")
        assert result == "a***@***.ru"


class TestTypedMaskCard:
    def test_16_digits_spaced(self):
        result = _typed_mask("4111 1111 1111 1111", "card_number")
        # Первые 6 цифр видны, последние 4 видны, 6 скрыты
        assert result.startswith("4111 11")
        assert result.endswith("1111")
        assert "*" in result


class TestTypedMaskPassport:
    def test_series_number(self):
        result = _typed_mask("4510 123456", "passport")
        # Первые 2 и последние 2 цифры видны
        assert result[0] == "4"
        assert result[1] == "5"
        assert "*" in result

    def test_foreign_passport(self):
        result = _typed_mask("72 1234567", "foreign_passport")
        assert "7" in result
        assert "*" in result


class TestTypedMaskINN:
    def test_inn_12(self):
        result = _typed_mask("770301234567", "inn")
        # Первые 3 и последние 2 видны
        assert result[:3] == "770"
        assert result[-2:] == "67"
        assert "*" in result

    def test_inn_10(self):
        result = _typed_mask("7703123456", "inn")
        assert result[:3] == "770"
        assert "*" in result


class TestTypedMaskDates:
    def test_birth_date_numeric(self):
        result = _typed_mask("01.01.1990", "birth_date")
        assert result == "**.**.**** "[:10]  # Все цифры маскируются
        assert result.count("*") == 8
        assert "." in result

    def test_issue_date(self):
        result = _typed_mask("15.03.2015", "issue_date")
        assert result.count("*") == 8


class TestTypedMaskCVVPIN:
    def test_cvv(self):
        assert _typed_mask("123", "cvv") == "***"

    def test_pin(self):
        assert _typed_mask("1234", "pin") == "****"


class TestTypedMaskAddress:
    def test_long_address(self):
        result = _typed_mask("г. Москва, ул. Ленина, д. 10, кв. 25", "address")
        assert result == "г. Москва,..."

    def test_short_address(self):
        result = _typed_mask("д. 10", "address")
        assert result == "д. ***"


class TestTypedMaskSNILS:
    def test_snils(self):
        result = _typed_mask("234-567-890 12", "snils")
        assert result[:3] == "234"
        assert "*" in result


class TestTypedMaskOMS:
    def test_oms(self):
        result = _typed_mask("1234567890123456", "oms")
        assert result[:3] == "123"
        assert result[-2:] == "56"
        assert "*" in result


class TestTypedMaskCardholderName:
    def test_cardholder(self):
        result = _typed_mask("IVANOV IVAN", "cardholder_name")
        assert result == "I. I."

    def test_cardholder_single(self):
        result = _typed_mask("IVANOV", "cardholder_name")
        assert result == "I."


class TestTypedMaskOther:
    def test_citizenship(self):
        result = _typed_mask("Российская Федерация", "citizenship")
        assert result == "Рос..."

    def test_issuing_authority(self):
        result = _typed_mask("УФМС по г. Москве", "issuing_authority")
        assert result == "УФМ..."

    def test_birth_place(self):
        result = _typed_mask("г. Новосибирск", "birth_place")
        assert result == "г. ..."

    def test_subdivision_code(self):
        result = _typed_mask("770-025", "subdivision_code")
        # 6 цифр: первые 3 видны, последние 2 видны, 1 скрыт
        assert "770" in result
        assert "*" in result


class TestTypedMaskDriversLicense:
    def test_dl(self):
        result = _typed_mask("77 14 567890", "drivers_license")
        assert "7" in result
        assert "*" in result


class TestTypedMaskMilitaryID:
    def test_military(self):
        result = _typed_mask("АБ 1234567", "military_id")
        assert "А" in result or "Б" in result
        assert "*" in result


# ─── mask_text(style="typed") integration tests ───


class TestMaskTextTyped:
    def test_fio_typed(self):
        text = "Иванов Иван Иванович обратился в банк."
        matches = detect(text)
        result = mask_text(text, matches, style="typed")
        assert "[ФИО:" in result.masked_text
        assert "И. И. И." in result.masked_text
        assert "Иванов" not in result.masked_text

    def test_phone_typed(self):
        text = "+7(999)123-45-67"
        matches = detect(text)
        result = mask_text(text, matches, style="typed")
        assert "[ТЕЛ:" in result.masked_text
        assert "*" in result.masked_text

    def test_email_typed(self):
        text = "email: user@mail.ru"
        matches = detect(text)
        result = mask_text(text, matches, style="typed")
        assert "[EMAIL:" in result.masked_text
        assert "u***@***.ru" in result.masked_text

    def test_card_cvv_typed(self):
        text = "Карта 4111 1111 1111 1111, CVV 123"
        matches = detect(text)
        result = mask_text(text, matches, style="typed")
        assert "[КАРТА:" in result.masked_text
        assert "[CVV:" in result.masked_text
        assert "*" in result.masked_text

    def test_inn_typed(self):
        text = "ИНН 770301234567"
        matches = detect(text)
        result = mask_text(text, matches, style="typed")
        assert "[ИНН:" in result.masked_text

    def test_passport_typed(self):
        text = "Паспорт серия 4510 номер 123456"
        matches = detect(text)
        result = mask_text(text, matches, style="typed")
        assert "[ПАСПОРТ:" in result.masked_text

    def test_birth_date_typed(self):
        text = "дата рождения 01.01.1990"
        matches = detect(text)
        result = mask_text(text, matches, style="typed")
        assert "[ДР:" in result.masked_text

    def test_snils_typed(self):
        text = "СНИЛС 234-567-890 12"
        matches = detect(text)
        result = mask_text(text, matches, style="typed")
        assert "[СНИЛС:" in result.masked_text

    def test_address_typed(self):
        text = "г. Москва, ул. Ленина, д. 10, кв. 25"
        matches = detect(text)
        result = mask_text(text, matches, style="typed")
        assert "[АДРЕС:" in result.masked_text

    def test_combo_typed(self):
        text = "Козлов Дмитрий Андреевич, тел. +7(916)123-45-67, email: test@example.com"
        matches = detect(text)
        result = mask_text(text, matches, style="typed")
        assert "[ФИО:" in result.masked_text
        assert "[ТЕЛ:" in result.masked_text
        assert "[EMAIL:" in result.masked_text
        # Ни одно реальное значение не должно остаться
        assert "Козлов" not in result.masked_text
        assert "916" not in result.masked_text

    def test_reverse_map_populated(self):
        text = "Иванов Иван Иванович"
        matches = detect(text)
        result = mask_text(text, matches, style="typed")
        assert len(result.reverse_map) >= 1
        # Ключ — typed placeholder, значение — оригинал
        for key, val in result.reverse_map.items():
            assert key.startswith("[")
            assert ":" in key
            assert val == "Иванов Иван Иванович"


# ─── Unmask typed tests ───


class TestUnmaskTyped:
    def test_unmask_fio(self):
        text = "Иванов Иван Иванович обратился в банк."
        matches = detect(text)
        result = mask_text(text, matches, style="typed")
        unmasked = unmask_text(result.masked_text, result.reverse_map)
        assert "Иванов Иван Иванович" in unmasked
        assert "[ФИО:" not in unmasked

    def test_unmask_combo(self):
        text = "Козлов Дмитрий Андреевич, email: test@example.com"
        matches = detect(text)
        result = mask_text(text, matches, style="typed")
        unmasked = unmask_text(result.masked_text, result.reverse_map)
        assert "Козлов Дмитрий Андреевич" in unmasked
        assert "test@example.com" in unmasked
        assert "[ФИО:" not in unmasked
        assert "[EMAIL:" not in unmasked

    def test_unmask_phone(self):
        text = "Звонок: +7(999)123-45-67"
        matches = detect(text)
        result = mask_text(text, matches, style="typed")
        unmasked = unmask_text(result.masked_text, result.reverse_map)
        assert "+7(999)123-45-67" in unmasked

    def test_unmask_preserves_unknown_placeholders(self):
        # Если в тексте есть placeholder, которого нет в reverse_map, он остаётся
        text = "[ФИО:И. И. И.] написал отчёт."
        unmasked = unmask_text(text, {})
        assert unmasked == text

    def test_roundtrip_all_styles(self):
        """Проверка: mask → unmask возвращает оригинал для каждого стиля."""
        original = "Козлов Дмитрий Андреевич, ИНН 770301234567"
        matches = detect(original)
        for style in ("placeholder", "typed"):
            result = mask_text(original, matches, style=style)
            unmasked = unmask_text(result.masked_text, result.reverse_map)
            assert unmasked == original, f"Roundtrip failed for style={style}"


# ─── Edge cases ───


class TestTypedMaskEdgeCases:
    def test_empty_value(self):
        assert _typed_mask("", "fio") == ""

    def test_no_matches(self):
        result = mask_text("Просто текст без ПДн", [], style="typed")
        assert result.masked_text == "Просто текст без ПДн"
        assert result.pd_count == 0

    def test_duplicate_values(self):
        """Одинаковые ФИО в тексте — одна и та же маска."""
        text = "Иванов Иван Иванович сказал: Иванов Иван Иванович подтвердил."
        matches = detect(text)
        result = mask_text(text, matches, style="typed")
        # Должно быть ровно 1 уникальная маска
        assert len(result.forward_map) == 1
        # Оба вхождения заменены
        assert result.masked_text.count("[ФИО:") == 2
