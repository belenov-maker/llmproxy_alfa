"""Тесты детектора ПДн — regex-эшелон.

≥60 тест-кейсов: позитивные, негативные, edge cases, Luhn.
"""

from __future__ import annotations

import pytest

from app.engine.detector import PDMatch, detect, _luhn_check


# ============================= Хелперы ======================================

def _categories(matches: list[PDMatch]) -> list[str]:
    """Вернуть список категорий из совпадений."""
    return [m.category for m in matches]


def _has(matches: list[PDMatch], category: str) -> bool:
    return any(m.category == category for m in matches)


def _get(matches: list[PDMatch], category: str) -> PDMatch | None:
    for m in matches:
        if m.category == category:
            return m
    return None


# ======================== 1. ФИО (fio) =====================================

class TestFio:
    def test_full_fio(self):
        """Полное ФИО: Иванов Иван Иванович."""
        r = detect("Клиент: Иванов Иван Иванович")
        assert _has(r, "fio")

    def test_full_fio_caps(self):
        """ФИО в верхнем регистре."""
        r = detect("ИВАНОВ ИВАН ИВАНОВИЧ")
        assert _has(r, "fio")

    def test_short_fio(self):
        """Сокращённое: Иванов И.И."""
        r = detect("Ответственный: Иванов И.И.")
        assert _has(r, "fio")

    def test_short_fio_spaced(self):
        """Сокращённое с пробелом: Иванов И. И."""
        r = detect("Подпись: Иванов И. И.")
        assert _has(r, "fio")

    def test_initials_first(self):
        """И.И. Иванов — инициалы впереди."""
        r = detect("Директор И.И. Иванов")
        assert _has(r, "fio")

    def test_double_surname(self):
        """Двойная фамилия: Петрова-Сидорова."""
        r = detect("Петрова-Сидорова Анна Викторовна")
        assert _has(r, "fio")

    def test_yo_letter(self):
        """Буква ё: Алёхин Пётр Сергеевич."""
        r = detect("Алёхин Пётр Сергеевич")
        assert _has(r, "fio")

    def test_two_words(self):
        """Фамилия Имя (2 слова)."""
        r = detect("Контакт: Смирнов Алексей")
        assert _has(r, "fio")

    def test_several_fio_in_sentence(self):
        """Несколько ФИО в одном предложении."""
        r = detect("Иванов Иван Иванович и Петрова Мария Сергеевна подписали договор")
        fio_matches = [m for m in r if m.category == "fio"]
        assert len(fio_matches) >= 2

    def test_not_fio_company(self):
        """ООО Газпром — не ФИО."""
        r = detect('ООО «Газпром»')
        assert not _has(r, "fio")

    def test_lowercase_fio_with_context(self):
        """ФИО в нижнем регистре с контекстом: фио иванов иван."""
        r = detect("фио: иванов иван")
        assert _has(r, "fio")

    def test_lowercase_fio_full(self):
        """ФИО в нижнем регистре с отчеством: клиент иванов иван иванович."""
        r = detect("клиент иванов иван иванович")
        assert _has(r, "fio")

    def test_lowercase_fio_no_context(self):
        """ФИО в нижнем регистре без контекста — не детектим."""
        r = detect("иванов иван")
        assert not _has(r, "fio")  # без контекста нельзя быть уверенным

    def test_lowercase_fio_abonent(self):
        """ФИО в нижнем регистре с контекстом «абонент»."""
        r = detect("абонент петров пётр петрович")
        assert _has(r, "fio")


# =================== 2. Дата рождения (birth_date) =========================

class TestBirthDate:
    def test_date_with_context(self):
        """Дата рождения: 01.02.1990."""
        r = detect("дата рождения: 01.02.1990")
        assert _has(r, "birth_date")

    def test_date_slash(self):
        """Через слэш: д.р. 01/02/1990."""
        r = detect("д.р. 01/02/1990")
        assert _has(r, "birth_date")

    def test_date_dash(self):
        """Через дефис: родился 15-03-1985."""
        r = detect("родился 15-03-1985")
        assert _has(r, "birth_date")

    def test_date_text_format(self):
        """Текстом: родился 1 января 1990."""
        r = detect("родился 1 января 1990")
        assert _has(r, "birth_date")

    def test_date_text_with_year_suffix(self):
        """Текстом с суффиксом: дата рождения 15 марта 2001 г."""
        r = detect("дата рождения 15 марта 2001 г.")
        assert _has(r, "birth_date")

    def test_no_context_no_match(self):
        """Без контекста рождения — не birth_date."""
        r = detect("дата: 01.01.2024")
        assert not _has(r, "birth_date")

    def test_date_iso_dot(self):
        """Дата рождения ISO: 1990.01.15."""
        r = detect("дата рождения 1990.01.15")
        assert _has(r, "birth_date")

    def test_date_iso_dash(self):
        """Дата рождения ISO: 1990-01-15."""
        r = detect("дата рождения 1990-01-15")
        assert _has(r, "birth_date")

    def test_date_iso_slash(self):
        """Дата рождения ISO: born 1985/03/20."""
        r = detect("born 1985/03/20")
        assert _has(r, "birth_date")


# ==================== 3. Место рождения (birth_place) =======================

class TestBirthPlace:
    def test_birth_place(self):
        """Место рождения: г. Москва."""
        r = detect("место рождения: г. Москва.")
        assert _has(r, "birth_place")

    def test_born_in(self):
        """Родился в г. Санкт-Петербурге."""
        r = detect("родился в г. Санкт-Петербурге.")
        assert _has(r, "birth_place")


# ======================== 4. Паспорт (passport) =============================

class TestPassport:
    def test_passport_with_context(self):
        """Паспорт серия 4509 123456."""
        r = detect("паспорт серия 4509 123456")
        assert _has(r, "passport")

    def test_passport_format_space(self):
        """Серия и номер: серия и номер 45 09 123456."""
        r = detect("серия и номер 45 09 123456")
        assert _has(r, "passport")

    def test_passport_no_context(self):
        """4509 123456 без контекста — низкий приоритет, но находится."""
        r = detect("4509 123456")
        assert _has(r, "passport")


# ===================== 5. Гражданство (citizenship) =========================

class TestCitizenship:
    def test_citizenship(self):
        """Гражданство: РФ."""
        r = detect("гражданство: РФ.")
        assert _has(r, "citizenship")

    def test_citizen(self):
        """Гражданин Российской Федерации."""
        r = detect("гражданин Российской Федерации.")
        assert _has(r, "citizenship")


# ================ 6. Орган выдачи (issuing_authority) =======================

class TestIssuingAuthority:
    def test_issuing_ovd(self):
        """Выдан ОВД района Хамовники."""
        r = detect("выдан ОВД района Хамовники г. Москвы")
        assert _has(r, "issuing_authority")

    def test_issuing_ufms(self):
        """Выдан УФМС России по г. Москве."""
        r = detect("выдан УФМС России по г. Москве")
        assert _has(r, "issuing_authority")


# ============== 7. Код подразделения (subdivision_code) =====================

class TestSubdivisionCode:
    def test_code_with_context(self):
        """Код подразделения 770-001."""
        r = detect("код подразделения 770-001")
        assert _has(r, "subdivision_code")

    def test_code_kp(self):
        """к/п 770-001."""
        r = detect("к/п 770-001")
        assert _has(r, "subdivision_code")


# =================== 8. Дата выдачи (issue_date) ===========================

class TestIssueDate:
    def test_issue_date(self):
        """Дата выдачи 15.04.2010."""
        r = detect("дата выдачи 15.04.2010")
        assert _has(r, "issue_date")

    def test_issued_date(self):
        """Выдан 20.05.2015."""
        r = detect("выдан 20.05.2015")
        assert _has(r, "issue_date")


# ============ 9. Водительское удостоверение (drivers_license) ===============

class TestDriversLicense:
    def test_drivers_license(self):
        """Водительское удостоверение 77 АА 123456."""
        r = detect("водительское удостоверение 77 АА 123456")
        assert _has(r, "drivers_license")

    def test_vu_short(self):
        """в/у 7700 123456."""
        r = detect("в/у 7700 123456")
        assert _has(r, "drivers_license")


# ======================== 10. Адрес (address) ===============================

class TestAddress:
    def test_street(self):
        """ул. Ленина, д. 5, кв. 12."""
        r = detect("ул. Ленина, д. 5, кв. 12")
        assert _has(r, "address")

    def test_prospekt(self):
        """проспект Мира, д. 10."""
        r = detect("проспект Мира, д. 10")
        assert _has(r, "address")

    def test_city_street(self):
        """г. Москва, ул. Тверская, д. 1."""
        r = detect("г. Москва, ул. Тверская, д. 1")
        assert _has(r, "address")

    def test_region(self):
        """Московская обл., г. Балашиха."""
        r = detect("Московская обл., г. Балашиха")
        assert _has(r, "address")

    def test_pereulok(self):
        """пер. Гагарина, д. 3."""
        r = detect("пер. Гагарина, д. 3")
        assert _has(r, "address")

    def test_only_street_prefix(self):
        """ул. Пушкина — адрес, не ФИО."""
        r = detect("ул. Пушкина, д. 5")
        assert _has(r, "address")


# ======================== 11. Email =========================================

class TestEmail:
    def test_simple_email(self):
        """user@example.com."""
        r = detect("контакт: user@example.com")
        assert _has(r, "email")

    def test_subdomain_email(self):
        """user@mail.example.com."""
        r = detect("user@mail.example.com")
        assert _has(r, "email")

    def test_email_with_dots(self):
        """ivan.petrov@company.ru."""
        r = detect("ivan.petrov@company.ru")
        assert _has(r, "email")


# ======================== 12. Телефон (phone) ===============================

class TestPhone:
    def test_phone_plus7(self):
        """+79161234567."""
        r = detect("+79161234567")
        assert _has(r, "phone")

    def test_phone_8(self):
        """89161234567."""
        r = detect("89161234567")
        assert _has(r, "phone")

    def test_phone_formatted(self):
        """+7(916)123-45-67."""
        r = detect("+7(916)123-45-67")
        assert _has(r, "phone")

    def test_phone_spaces(self):
        """8 916 123 45 67."""
        r = detect("8 916 123 45 67")
        assert _has(r, "phone")

    def test_phone_in_sentence(self):
        """Телефон в предложении."""
        r = detect("Мой телефон: +7-916-123-45-67, звоните")
        assert _has(r, "phone")


# ========================== 13. ИНН (inn) ===================================

class TestInn:
    def test_inn_12_ctx(self):
        """ИНН 770102345678 (физлицо)."""
        r = detect("ИНН 770102345678")
        assert _has(r, "inn")

    def test_inn_10_ctx(self):
        """ИНН 7701234567 (юрлицо)."""
        r = detect("ИНН 7701234567")
        assert _has(r, "inn")

    def test_inn_lowercase(self):
        """инн 770102345678."""
        r = detect("инн 770102345678")
        assert _has(r, "inn")

    def test_inn_bare_invalid_checksum(self):
        """Без контекста, невалидная контрольная сумма — не ИНН."""
        r = detect("111111111111")  # 12 цифр, но не валидный ИНН
        assert not _has(r, "inn")

    def test_inn_ctx_always_detected(self):
        """С контекстом ИНН — детектим даже с невалидной суммой."""
        r = detect("ИНН 111111111111")
        assert _has(r, "inn")  # с контекстом оставляем


# =================== 14. Номер карты (card_number) ==========================

class TestCardNumber:
    def test_card_luhn_valid(self):
        """Карта 4111 1111 1111 1111 — Luhn валидна → confidence=1.0."""
        r = detect("карта 4111 1111 1111 1111")
        match = _get(r, "card_number")
        assert match is not None
        assert match.confidence == 1.0

    def test_card_luhn_invalid(self):
        """Карта 4111 1111 1111 1112 — Luhn невалидна → отбрасываем."""
        r = detect("карта 4111 1111 1111 1112")
        match = _get(r, "card_number")
        assert match is None  # non-Luhn карты теперь отсекаются

    def test_card_dashes(self):
        """Карта через дефисы: 5500-0000-0000-0004 (Luhn valid)."""
        r = detect("5500-0000-0000-0004")
        match = _get(r, "card_number")
        assert match is not None
        assert match.confidence == 1.0

    def test_card_no_spaces(self):
        """Слитно: 4111111111111111 (Luhn valid)."""
        r = detect("4111111111111111")
        match = _get(r, "card_number")
        assert match is not None
        assert match.confidence == 1.0

    def test_card_starts_with_1_no_match(self):
        """Карты с 1 не бывает (ISO 7812)."""
        r = detect("1234 5678 9012 3456")
        assert not _has(r, "card_number")


# =========================== 15. CVV (cvv) ==================================

class TestCvv:
    def test_cvv_with_card(self):
        """CVV с контекстом карты."""
        r = detect("Карта 4111 1111 1111 1111, CVV: 123")
        assert _has(r, "cvv")

    def test_cvc_with_card(self):
        """СVC с контекстом карты."""
        r = detect("Карта 4111 1111 1111 1111, CVC 456")
        assert _has(r, "cvv")

    def test_cvv_without_card_not_detected(self):
        """CVV без контекста карты не маскируется."""
        r = detect("CVV: 123")
        assert not _has(r, "cvv")


# ========================== 16. ПИН (pin) ===================================

class TestPin:
    def test_pin_with_card(self):
        """ПИН с контекстом карты."""
        r = detect("Карта 4111 1111 1111 1111, ПИН: 5678")
        assert _has(r, "pin")

    def test_pin_en_with_card(self):
        """PIN с контекстом карты."""
        r = detect("Карта 4111 1111 1111 1111, PIN 5678")
        assert _has(r, "pin")

    def test_pin_without_card_not_detected(self):
        """ПИН без контекста карты не маскируется."""
        r = detect("ПИН: 1234")
        assert not _has(r, "pin")


# ============== 17. Имя держателя карты (cardholder_name) ===================

class TestCardholderName:
    def test_cardholder(self):
        """cardholder: IVANOV IVAN."""
        r = detect("cardholder: IVANOV IVAN")
        assert _has(r, "cardholder_name")

    def test_holder_ru(self):
        """Держатель: PETROV SERGEY."""
        r = detect("держатель: PETROV SERGEY")
        assert _has(r, "cardholder_name")


# ======================== 18. СНИЛС (snils) =================================

class TestSnils:
    def test_snils_dashes(self):
        """123-456-789 00."""
        r = detect("СНИЛС: 123-456-789 00")
        assert _has(r, "snils")

    def test_snils_bare(self):
        """СНИЛС 12345678900."""
        r = detect("СНИЛС 12345678900")
        assert _has(r, "snils")

    def test_snils_no_space(self):
        """123-456-78900."""
        r = detect("123-456-78900")
        assert _has(r, "snils")


# ======================== 19. Полис ОМС (oms) ===============================

class TestOms:
    def test_oms(self):
        """ОМС 1234567890123456."""
        r = detect("ОМС 1234567890123456")
        assert _has(r, "oms")

    def test_medical_policy(self):
        """Медицинский полис 1234567890123456."""
        r = detect("медицинский полис 1234567890123456")
        assert _has(r, "oms")


# ============= 20. Загранпаспорт (foreign_passport) ========================

class TestForeignPassport:
    def test_foreign_passport(self):
        """Загранпаспорт 51 1234567."""
        r = detect("загранпаспорт 51 1234567")
        assert _has(r, "foreign_passport")

    def test_foreign_passport_no(self):
        """Заграничный паспорт 52 No1234567."""
        r = detect("заграничный паспорт 52 No1234567")
        assert _has(r, "foreign_passport")


# =============== 21. Военный билет (military_id) ============================

class TestMilitaryId:
    def test_military_id(self):
        """Военный билет АА 1234567."""
        r = detect("военный билет АА 1234567")
        assert _has(r, "military_id")

    def test_military_short(self):
        """в/б АБ 9876543."""
        r = detect("в/б АБ 9876543")
        assert _has(r, "military_id")


# =================== Negative / Anti-FP ====================================

class TestNegative:
    def test_empty_string(self):
        """Пустая строка → пустой список."""
        assert detect("") == []

    def test_whitespace_only(self):
        """Только пробелы → пустой список."""
        assert detect("   \t\n  ") == []

    def test_long_number_no_fp(self):
        """Длинное число — не false positive для карты."""
        r = detect("12345678901234567890")
        # Начинается с 1 — не попадает под карту (ISO 7812)
        assert not _has(r, "card_number")

    def test_date_without_birth_context(self):
        """Просто дата без контекста — не birth_date."""
        r = detect("дата документа: 01.01.2024")
        assert not _has(r, "birth_date")

    def test_company_name_not_fio(self):
        """ООО «Ромашка» — не ФИО."""
        r = detect('Компания ООО «Ромашка» заключила договор')
        assert not _has(r, "fio")


# ====================== Edge Cases ==========================================

class TestEdgeCases:
    def test_multiline(self):
        """Текст с переносами строк."""
        text = "ФИО: Иванов Иван Иванович\nТелефон: +79161234567\nEmail: test@mail.ru"
        r = detect(text)
        cats = _categories(r)
        assert "fio" in cats
        assert "phone" in cats
        assert "email" in cats

    def test_tabs(self):
        """Текст с табами."""
        r = detect("паспорт\t4509 123456")
        assert _has(r, "passport")

    def test_mixed_languages(self):
        """Смешанный текст (русский + английский)."""
        r = detect("Client Иванов Иван Иванович, email: test@example.com")
        assert _has(r, "fio")
        assert _has(r, "email")

    def test_multiple_pd_in_text(self):
        """Несколько ПДн: ФИО + паспорт + телефон."""
        text = (
            "Клиент: Иванов Иван Иванович, "
            "паспорт серия 4509 123456, "
            "тел. +79161234567"
        )
        r = detect(text)
        cats = _categories(r)
        assert "fio" in cats
        assert "passport" in cats
        assert "phone" in cats

    def test_passport_without_keyword(self):
        """4509 123456 без ключевого слова — находит с низким приоритетом."""
        r = detect("номер 4509 123456")
        assert _has(r, "passport")

    def test_phone_various_formats(self):
        """Разные форматы телефона."""
        for phone in ["+7(916)123-45-67", "8 916 123 45 67", "89161234567",
                      "+7-916-123-45-67"]:
            r = detect(phone)
            assert _has(r, "phone"), f"Не найден телефон в '{phone}'"

    def test_snils_both_formats(self):
        """СНИЛС с дефисами и без."""
        r1 = detect("123-456-789 00")
        assert _has(r1, "snils")
        r2 = detect("СНИЛС 12345678900")
        assert _has(r2, "snils")


# ===================== Luhn-функция =========================================

class TestLuhn:
    def test_luhn_valid_number(self):
        """4111111111111111 — Luhn валидна."""
        assert _luhn_check("4111111111111111") is True

    def test_luhn_invalid_number(self):
        """4111111111111112 — Luhn невалидна."""
        assert _luhn_check("4111111111111112") is False

    def test_luhn_short(self):
        """Короткий номер — не проходит."""
        assert _luhn_check("1234") is False

    def test_luhn_known_test_card(self):
        """4111 1111 1111 1111 — тестовая карта, Luhn валидна."""
        assert _luhn_check("4111111111111111") is True


# ==================== Дедупликация ==========================================

class TestDeduplication:
    def test_overlapping_passport(self):
        """Паспорт с контекстом и без — дедупликация оставляет один."""
        r = detect("паспорт 4509 123456")
        passport_matches = [m for m in r if m.category == "passport"]
        assert len(passport_matches) == 1

    def test_higher_priority_wins(self):
        """При перекрытии побеждает правило с высшим приоритетом."""
        r = detect("паспорт 4509 123456")
        match = _get(r, "passport")
        assert match is not None
        # Должно быть правило с контекстом (priority=90)
        assert "контекст" in match.rule.lower() or match.confidence == 0.9
