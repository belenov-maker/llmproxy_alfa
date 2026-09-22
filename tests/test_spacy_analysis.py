"""SpaCy-верифицированные тесты маскирования ПДн.

Тесты основаны на результатах анализа scripts/spacy_analysis.py:
- Проверка корректности обнаружения ПДн (True Positives)
- Проверка Anti-FP фильтра (известные личности, организации, персонажи)
- Проверка пограничных случаев (issuing_authority + issue_date overlap)
"""

import pytest
from app.engine.detector import detect


# ─── Позитивные тесты: ПДн корректно обнаруживаются ───────────────────


class TestSpacyPositives:
    """Тесты на корректное обнаружение ПДн (SpaCy-верифицированные TP)."""

    def test_fio_full(self):
        matches = detect("Иванов Иван Иванович обратился в банк.")
        cats = {m.category for m in matches}
        assert "fio" in cats

    def test_fio_female(self):
        matches = detect("Заявление от Петровой Марии Сергеевны.")
        cats = {m.category for m in matches}
        assert "fio" in cats

    def test_fio_initials(self):
        matches = detect("Сидоров А.В. подписал договор.")
        cats = {m.category for m in matches}
        assert "fio" in cats

    def test_fio_with_title(self):
        """ФИО с должностью — ФИО должно определяться, должность нет."""
        matches = detect("Директор Козлов Дмитрий Петрович назначил совещание.")
        cats = {m.category for m in matches}
        assert "fio" in cats

    def test_passport_with_context(self):
        matches = detect("Иванов Иван Иванович, паспорт серия 4510 номер 123456.")
        cats = {m.category for m in matches}
        assert "fio" in cats
        assert "passport" in cats

    def test_passport_organ_date(self):
        """Критический тест: issuing_authority + issue_date не перекрывают друг друга."""
        text = "Паспортные данные: серия 4510 номер 654321, выдан ОВД района Тверской 15.03.2015."
        matches = detect(text)
        cats = {m.category for m in matches}
        assert "passport" in cats, f"Ожидался passport, найдены: {cats}"
        assert "issuing_authority" in cats, f"Ожидался issuing_authority, найдены: {cats}"
        assert "issue_date" in cats, f"Ожидался issue_date, найдены: {cats}"

    def test_phone_email(self):
        matches = detect("Телефон: +7 (495) 123-45-67, email: test@example.com")
        cats = {m.category for m in matches}
        assert "phone" in cats
        assert "email" in cats

    def test_phone_8format(self):
        matches = detect("Звоните по номеру 8-916-555-12-34.")
        cats = {m.category for m in matches}
        assert "phone" in cats

    def test_card_cvv(self):
        matches = detect("Номер карты: 4111 1111 1111 1111, CVV: 123")
        cats = {m.category for m in matches}
        assert "card_number" in cats
        assert "cvv" in cats

    def test_inn(self):
        matches = detect("ИНН: 770123456789")
        cats = {m.category for m in matches}
        assert "inn" in cats

    def test_snils(self):
        matches = detect("СНИЛС: 123-456-789 00")
        cats = {m.category for m in matches}
        assert "snils" in cats

    def test_address_full(self):
        matches = detect("Адрес: г. Москва, ул. Тверская, д. 15, кв. 42.")
        cats = {m.category for m in matches}
        assert "address" in cats

    def test_address_region(self):
        matches = detect("Проживает по адресу: Московская обл., г. Подольск, ул. Ленина, д. 5.")
        cats = {m.category for m in matches}
        assert "address" in cats

    def test_birth_date_numeric(self):
        matches = detect("Дата рождения: 15.06.1990")
        cats = {m.category for m in matches}
        assert "birth_date" in cats

    def test_birth_date_text(self):
        matches = detect("Родился 25 декабря 1985 года.")
        cats = {m.category for m in matches}
        assert "birth_date" in cats

    def test_birthplace_citizenship(self):
        matches = detect("Место рождения: г. Новосибирск, гражданство: Российская Федерация.")
        cats = {m.category for m in matches}
        assert "birth_place" in cats
        assert "citizenship" in cats

    def test_subdivision_organ_date(self):
        matches = detect("Код подразделения: 770-025, выдан УФМС по г. Москве 20.05.2018.")
        cats = {m.category for m in matches}
        assert "subdivision_code" in cats
        assert "issuing_authority" in cats
        assert "issue_date" in cats

    def test_drivers_license(self):
        matches = detect("Водительское удостоверение: 77 14 567890.")
        cats = {m.category for m in matches}
        assert "drivers_license" in cats

    def test_military_id(self):
        matches = detect("Военный билет: АБ 1234567.")
        cats = {m.category for m in matches}
        assert "military_id" in cats

    def test_combo_full_client(self):
        text = (
            "Клиент Козлов Дмитрий Андреевич, дата рождения 12.03.1988, "
            "паспорт серия 4515 номер 987654, СНИЛС 111-222-333 44, "
            "проживает: г. Москва, ул. Арбат, д. 10, кв. 5. "
            "Телефон: +7 (916) 111-22-33, email: kozlov@mail.ru"
        )
        matches = detect(text)
        cats = {m.category for m in matches}
        for expected in ["fio", "birth_date", "passport", "snils", "address", "phone", "email"]:
            assert expected in cats, f"Ожидался {expected}, найдены: {cats}"

    def test_combo_inn_oms_zagran(self):
        text = (
            "Заёмщик: Морозова Елена Викторовна, ИНН 501234567890, "
            "полис ОМС 1234567890123456, загранпаспорт 72 1234567."
        )
        matches = detect(text)
        cats = {m.category for m in matches}
        for expected in ["fio", "inn", "oms", "foreign_passport"]:
            assert expected in cats, f"Ожидался {expected}, найдены: {cats}"


# ─── Anti-FP тесты: НЕ должны маскироваться ───────────────────────────


class TestSpacyAntiFP:
    """Anti-FP: известные личности, персонажи, организации — не ПДн."""

    def test_pushkin_not_masked(self):
        """Александр Сергеевич Пушкин — не персональные данные."""
        matches = detect("Александр Сергеевич Пушкин написал Евгения Онегина.")
        fio_matches = [m for m in matches if m.category == "fio"]
        assert len(fio_matches) == 0, f"FP: найдены ФИО {[m.value for m in fio_matches]}"

    def test_ooo_not_masked(self):
        """ООО Ромашка — не персональные данные."""
        matches = detect("Компания ООО Ромашка зарегистрирована в 2020 году.")
        fio_matches = [m for m in matches if m.category == "fio"]
        assert len(fio_matches) == 0, f"FP: найдены ФИО {[m.value for m in fio_matches]}"

    def test_president_not_masked(self):
        """Президент Путин — публичная фигура, не ПДн."""
        matches = detect("Президент Владимир Путин выступил с речью.")
        fio_matches = [m for m in matches if m.category == "fio"]
        assert len(fio_matches) == 0, f"FP: найдены ФИО {[m.value for m in fio_matches]}"

    def test_tolstoy_not_masked(self):
        matches = detect("Лев Николаевич Толстой написал Войну и мир.")
        fio_matches = [m for m in matches if m.category == "fio"]
        assert len(fio_matches) == 0, f"FP: найдены ФИО {[m.value for m in fio_matches]}"

    def test_mendeleev_not_masked(self):
        matches = detect("Дмитрий Иванович Менделеев создал периодическую таблицу.")
        fio_matches = [m for m in matches if m.category == "fio"]
        assert len(fio_matches) == 0, f"FP: найдены ФИО {[m.value for m in fio_matches]}"

    def test_gagarin_not_masked(self):
        matches = detect("Юрий Алексеевич Гагарин полетел в космос.")
        fio_matches = [m for m in matches if m.category == "fio"]
        assert len(fio_matches) == 0, f"FP: найдены ФИО {[m.value for m in fio_matches]}"

    def test_raskolnikov_not_masked(self):
        """Родион Раскольников — литературный персонаж."""
        matches = detect("Родион Раскольников — персонаж Достоевского.")
        fio_matches = [m for m in matches if m.category == "fio"]
        assert len(fio_matches) == 0, f"FP: найдены ФИО {[m.value for m in fio_matches]}"

    def test_bolkonsky_not_masked(self):
        """Князь Андрей Болконский — литературный персонаж."""
        matches = detect("Князь Андрей Болконский смотрел на небо.")
        fio_matches = [m for m in matches if m.category == "fio"]
        assert len(fio_matches) == 0, f"FP: найдены ФИО {[m.value for m in fio_matches]}"

    def test_pao_sberbank_not_masked(self):
        """ПАО Сбербанк — организация, не ФИО."""
        matches = detect("ПАО Сбербанк выпустил новую карту.")
        fio_matches = [m for m in matches if m.category == "fio"]
        assert len(fio_matches) == 0, f"FP: найдены ФИО {[m.value for m in fio_matches]}"

    def test_toponym_not_masked(self):
        """Санкт-Петербург без контекста адреса — не ПДн."""
        matches = detect("В городе Санкт-Петербург проходит фестиваль.")
        assert len(matches) == 0, f"FP: найдены ПДн {[(m.category, m.value) for m in matches]}"

    def test_temperature_not_masked(self):
        """Числовые данные без контекста ПДн — не маскируются."""
        matches = detect("Температура воздуха составила 25 градусов.")
        assert len(matches) == 0, f"FP: найдены ПДн {[(m.category, m.value) for m in matches]}"

    def test_real_fio_still_detected(self):
        """Обычное ФИО (не из стоп-листа) по-прежнему обнаруживается."""
        matches = detect("Козлов Дмитрий Андреевич, паспорт 4515 123456")
        fio_matches = [m for m in matches if m.category == "fio"]
        assert len(fio_matches) >= 1, "Реальное ФИО должно обнаруживаться"
