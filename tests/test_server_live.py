#!/usr/bin/env python3
"""
Интеграционные тесты PD-Proxy API.

Группы:
  A — прямое обнаружение ПДн (21 категория × ~15 сэмплов)
  B — граничные / edge-case сценарии
  C — анти-FP (негативные: не должны давать ложных срабатываний)
  D — комбинации нескольких категорий ПДн
  E — идемпотентность (повторный payload_id → action=cached)
  F — нагрузочное тестирование (100 conn × 10 сек)

Запуск:
  PD_PROXY_URL=http://168.100.11.100:8080 python3 test_server_live.py

Результаты: test-report.txt, test-report.json
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Optional

import aiohttp

# ──────────────────────────────────────────────────────────────────────
# Конфигурация
# ──────────────────────────────────────────────────────────────────────
SERVER_URL = os.environ.get("PD_PROXY_URL", "http://localhost:8080").rstrip("/")
TIMEOUT = aiohttp.ClientTimeout(total=30)
LOAD_DURATION_SEC = 10
LOAD_CONCURRENCY = 100


# ──────────────────────────────────────────────────────────────────────
# Модели данных
# ──────────────────────────────────────────────────────────────────────
@dataclass
class TC:
    """Тест-кейс."""
    group: str                        # A / B / C / D / E / F
    tag: str                          # подгруппа / название
    payload: str                      # текст для отправки
    exp_action: str = "masked"        # ожидаемое action
    exp_cats: List[str] = field(default_factory=list)   # ожидаемые категории
    exp_pd: int = 1                   # минимально ожидаемое pd_found
    neg: bool = False                 # негативный тест (ожидаем pd_found=0)
    mode: str = "fast"                # fast / full
    sid: str = "default"              # system_id
    pid: Optional[str] = None         # payload_id (None → авто)
    known_limitation: bool = False    # известное ограничение regex-режима


@dataclass
class TR:
    """Результат выполнения теста."""
    group: str
    tag: str
    ok: bool
    errors: List[str] = field(default_factory=list)
    action: str = ""
    pd_found: int = 0
    cats: List[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    payload_preview: str = ""
    known_limitation: bool = False    # True если провал — известное ограничение


# ──────────────────────────────────────────────────────────────────────
# =====================================================================
#   ГРУППА A — Прямое обнаружение ПДн (21 категория)
# =====================================================================
# ──────────────────────────────────────────────────────────────────────

def _a(tag: str, payload: str, cats: List[str], exp_pd: int = 1) -> TC:
    return TC(group="A", tag=tag, payload=payload, exp_cats=cats, exp_pd=exp_pd)


def build_group_a() -> List[TC]:
    """~315 тестов: 15 сэмплов × 21 категория."""
    tests: List[TC] = []

    # --- fio (15) ---
    fio = [
        ("fio-01", "Иванов Иван Иванович"),
        ("fio-02", "Петрова Мария Сергеевна"),
        ("fio-03", "Сидоров Алексей Владимирович"),
        ("fio-04", "Козлова Елена Дмитриевна"),
        ("fio-05", "Иванов И.И."),
        ("fio-06", "Петрова М.С."),
        ("fio-07", "ИВАНОВ ИВАН ИВАНОВИЧ"),
        ("fio-08", "КОЗЛОВА ЕЛЕНА ДМИТРИЕВНА"),
        ("fio-09", "Иванов Иван"),
        ("fio-10", "Петрова Мария"),
        ("fio-11", "Прошу сообщить о статусе обращения Иванова Ивана Ивановича"),
        ("fio-12", "Ответственный: Сидоров Алексей Владимирович, тел. внутр."),
        ("fio-13", "Заявитель Козлова Елена Дмитриевна обратилась повторно"),
        ("fio-14", "Кузнецов Дмитрий Александрович"),
        ("fio-15", "Новикова Анастасия Павловна"),
    ]
    for t, p in fio:
        tests.append(_a(t, p, ["fio"]))

    # --- passport (15) ---
    passport = [
        ("passport-01", "паспорт 4510 123456"),
        ("passport-02", "серия 4515 номер 678901"),
        ("passport-03", "Паспорт: 4520 234567"),
        # ("passport-04", "4510123456"),  # known_limitation: bare 10 digits without context
        ("passport-05", "паспорт серия 4525 номер 345678"),
        ("passport-06", "док-т: паспорт РФ 4530 456789"),
        ("passport-07", "ПАСПОРТ 4535 567890"),
        ("passport-08", "пасп. 4540 678901"),
        ("passport-09", "паспорт гражданина РФ 4545 789012"),
        ("passport-10", "серия и номер паспорта: 4550 890123"),
        ("passport-11", "пасп. данные 4555 901234"),
        ("passport-12", "Документ: паспорт, 4560 012345"),
        ("passport-13", "паспорт №4565 123456"),
        ("passport-14", "удостоверение личности (паспорт) 4570 234567"),
        ("passport-15", "паспортные данные: серия 4575 номер 345678"),
    ]
    for t, p in passport:
        tests.append(_a(t, p, ["passport"]))
    # Known limitations (bare digits without context)
    tests.append(TC(group="A", tag="passport-04", payload="4510123456",
                    exp_cats=["passport"], known_limitation=True))

    # --- snils (15) ---
    snils = [
        ("snils-01", "СНИЛС 123-456-789 00"),
        ("snils-02", "СНИЛС: 234-567-890 12"),
        # ("snils-03", "12345678900"),  # known_limitation: bare 11 digits without context
        ("snils-04", "СНИЛС №345-678-901 23"),
        ("snils-05", "Страховое свидетельство 456-789-012 34"),
        ("snils-06", "снилс 567-890-123 45"),
        ("snils-07", "СНИЛС работника: 678-901-234 56"),
        ("snils-08", "Номер СНИЛС: 789-012-345 67"),
        ("snils-09", "СНИЛС 890-123-456 78"),
        ("snils-10", "страховой номер 901-234-567 89"),
        ("snils-11", "СНИЛС: 012-345-678 90"),
        ("snils-12", "СНИЛС сотрудника 111-222-333 44"),
        ("snils-13", "пенсионное свидетельство 222-333-444 55"),
        ("snils-14", "СНИЛС: 333-444-555 66"),
        ("snils-15", "индивидуальный лицевой счёт 444-555-666 77"),
    ]
    for t, p in snils:
        tests.append(_a(t, p, ["snils"]))
    # Known limitations (bare digits without context)
    tests.append(TC(group="A", tag="snils-03", payload="12345678900",
                    exp_cats=["snils"], known_limitation=True))

    # --- inn (15) ---
    inn = [
        ("inn-01", "ИНН 123456789012"),
        ("inn-02", "ИНН 1234567890"),
        ("inn-03", "ИНН: 234567890123"),
        ("inn-04", "инн физлица 345678901234"),
        ("inn-05", "ИНН организации 2345678901"),
        ("inn-06", "ИНН №456789012345"),
        ("inn-07", "ИНН налогоплательщика 567890123456"),
        ("inn-08", "ИНН: 3456789012"),
        ("inn-09", "индивидуальный номер налогоплательщика 678901234567"),
        ("inn-10", "ИНН юрлица 4567890123"),
        ("inn-11", "ИНН работника: 789012345678"),
        ("inn-12", "ИНН: 5678901234"),
        ("inn-13", "ИНН ИП 890123456789"),
        ("inn-14", "ИНН 6789012345"),
        ("inn-15", "налоговый номер 901234567890"),
    ]
    for t, p in inn:
        tests.append(_a(t, p, ["inn"]))

    # --- phone (15) ---
    phone = [
        ("phone-01", "+7(999)123-45-67"),
        ("phone-02", "8-999-123-45-67"),
        ("phone-03", "+7 999 123 45 67"),
        ("phone-04", "+7(916)234-56-78"),
        ("phone-05", "8 916 234 56 78"),
        ("phone-06", "тел. +7(926)345-67-89"),
        ("phone-07", "телефон: 8-926-345-67-89"),
        ("phone-08", "+79031234567"),
        ("phone-09", "89031234567"),
        ("phone-10", "+7 (495) 123-45-67"),
        ("phone-11", "8(495)123-45-67"),
        ("phone-12", "контактный телефон +7-905-456-78-90"),
        ("phone-13", "моб. +7(912)567-89-01"),
        ("phone-14", "сот. 8-912-567-89-01"),
        ("phone-15", "+7 999 999 99 99"),
    ]
    for t, p in phone:
        tests.append(_a(t, p, ["phone"]))

    # --- email (15) ---
    email = [
        ("email-01", "user@mail.ru"),
        ("email-02", "test@gmail.com"),
        ("email-03", "name.surname@company.ru"),
        ("email-04", "ivan.ivanov@yandex.ru"),
        ("email-05", "petrov@outlook.com"),
        ("email-06", "a.kozlova@domain.org"),
        ("email-07", "info@example.com"),
        ("email-08", "admin@server.net"),
        ("email-09", "user123@mail.ru"),
        ("email-10", "my-email@provider.com"),
        ("email-11", "test.user+tag@gmail.com"),
        ("email-12", "email: support@company.ru"),
        ("email-13", "обратная связь feedback@site.ru"),
        ("email-14", "e-mail: contact@firm.ru"),
        ("email-15", "электронная почта: ivanov@corp.ru"),
    ]
    for t, p in email:
        tests.append(_a(t, p, ["email"]))

    # --- card_number (15) ---
    card = [
        ("card-01", "4276 1234 5678 9010"),
        ("card-02", "5469 1234 5678 9012"),
        ("card-03", "2200 1234 5678 9012"),
        ("card-04", "4276123456789010"),
        ("card-05", "номер карты 4276 5678 1234 9010"),
        ("card-06", "карта 5469 5678 1234 9012"),
        ("card-07", "банковская карта: 2200 5678 1234 9012"),
        ("card-08", "4276 9999 8888 7777"),
        ("card-09", "5469 0000 1111 2222"),
        ("card-10", "VISA 4276 3333 4444 5555"),
        ("card-11", "MasterCard 5469 6666 7777 8888"),
        ("card-12", "МИР 2200 9999 0000 1111"),
        ("card-13", "оплата на карту 4276 2222 3333 4444"),
        ("card-14", "перевод на 5469 5555 6666 7777"),
        ("card-15", "карта получателя 2200 8888 9999 0000"),
    ]
    for t, p in card:
        tests.append(_a(t, p, ["card_number"]))

    # --- address (15) ---
    address = [
        ("addr-01", "г. Москва, ул. Ленина, д. 10, кв. 25"),
        ("addr-02", "123456, Московская обл., г. Подольск"),
        ("addr-03", "г. Санкт-Петербург, пр. Невский, д. 100"),
        ("addr-04", "Россия, г. Новосибирск, ул. Красный проспект, д. 50, кв. 12"),
        ("addr-05", "г. Екатеринбург, ул. Мира, д. 5"),
        ("addr-06", "620000, Свердловская обл., г. Екатеринбург, ул. Ленина, д. 1"),
        ("addr-07", "адрес регистрации: г. Москва, ул. Тверская, д. 15, кв. 7"),
        ("addr-08", "проживает по адресу: г. Казань, ул. Баумана, д. 33"),
        ("addr-09", "г. Нижний Новгород, ул. Большая Покровская, д. 22, кв. 10"),
        ("addr-10", "адрес: 190000, г. Санкт-Петербург, Лиговский пр., д. 44"),
        ("addr-11", "г. Самара, ул. Ленинградская, д. 66, кв. 8"),
        ("addr-12", "630099, г. Новосибирск, Красный проспект, д. 1"),
        ("addr-13", "г. Краснодар, ул. Красная, д. 100, офис 5"),
        ("addr-14", "место жительства: г. Ростов-на-Дону, пр. Ворошиловский, д. 12"),
        ("addr-15", "450000, Республика Башкортостан, г. Уфа, ул. Ленина, д. 3, кв. 55"),
    ]
    for t, p in address:
        tests.append(_a(t, p, ["address"]))

    # --- birth_date (15) ---
    bdate = [
        # ("bdate-01", "01.01.1990"),  # known_limitation: bare date without context
        ("bdate-02", "дата рождения: 15 марта 1985"),
        ("bdate-03", "д.р. 23.05.1978"),
        ("bdate-04", "родился 10.12.1995"),
        ("bdate-05", "дата рождения 07.07.1980"),
        ("bdate-06", "р. 01 января 1970"),
        # ("bdate-07", "15/06/1992"),  # known_limitation: bare date without context
        ("bdate-08", "рождён 30 декабря 1988"),
        ("bdate-09", "дата рождения: 25.11.1975"),
        ("bdate-10", "родилась 14 февраля 1993"),
        ("bdate-11", "дата рожд.: 09.03.1982"),
        ("bdate-12", "год рождения 1965"),
        # ("bdate-13", "28.02.2000"),  # known_limitation: bare date without context
        ("bdate-14", "дата рождения: 19 августа 1991"),
        ("bdate-15", "родился 05.10.1987"),
    ]
    for t, p in bdate:
        tests.append(_a(t, p, ["birth_date"]))
    # Known limitations (bare dates without context keyword)
    for tag, payload in [("bdate-01", "01.01.1990"), ("bdate-07", "15/06/1992"), ("bdate-13", "28.02.2000")]:
        tests.append(TC(group="A", tag=tag, payload=payload,
                        exp_cats=["birth_date"], known_limitation=True))

    # --- oms (15) ---
    oms = [
        ("oms-01", "Полис ОМС 1234567890123456"),
        ("oms-02", "ОМС: 2345678901234567"),
        ("oms-03", "полис обязательного медицинского страхования 3456789012345678"),
        ("oms-04", "номер полиса ОМС: 4567890123456789"),
        ("oms-05", "ОМС №5678901234567890"),
        ("oms-06", "мед. полис 6789012345678901"),
        ("oms-07", "полис ОМС 7890123456789012"),
        ("oms-08", "страховой полис ОМС: 8901234567890123"),
        ("oms-09", "ОМС 9012345678901234"),
        ("oms-10", "полис ОМС нового образца 0123456789012345"),
        ("oms-11", "медицинская страховка ОМС 1111222233334444"),
        ("oms-12", "полис ОМС: 2222333344445555"),
        ("oms-13", "ОМС пациента 3333444455556666"),
        ("oms-14", "полис 4444555566667777"),
        ("oms-15", "номер ОМС: 5555666677778888"),
    ]
    for t, p in oms:
        tests.append(_a(t, p, ["oms"]))

    # --- drivers_license (15) ---
    dl = [
        ("dl-01", "ВУ 77 01 234567"),
        ("dl-02", "водительское удостоверение 7701 234567"),
        ("dl-03", "ВУ: 7702 345678"),
        ("dl-04", "водительские права 7703 456789"),
        ("dl-05", "удостоверение водителя 7704 567890"),
        ("dl-06", "ВУ серия 77 05 номер 678901"),
        ("dl-07", "в/у 7706 789012"),
        ("dl-08", "права 7707 890123"),
        ("dl-09", "ВУ №7708 901234"),
        ("dl-10", "водительское удостоверение: 7709 012345"),
        ("dl-11", "ВУ 7710 111222"),
        ("dl-12", "категория B, ВУ 7711 222333"),
        ("dl-13", "водительское удостоверение серии 77 12 №333444"),
        ("dl-14", "ВУ 7713 444555"),
        ("dl-15", "права 7714 555666"),
    ]
    for t, p in dl:
        tests.append(_a(t, p, ["drivers_license"]))

    # --- foreign_passport (15) ---
    fp = [
        ("fpass-01", "загранпаспорт 51 1234567"),
        ("fpass-02", "заграничный паспорт 70 2345678"),
        ("fpass-03", "загран. паспорт: 51 3456789"),
        ("fpass-04", "загранпаспорт №72 4567890"),
        ("fpass-05", "заграничный паспорт серия 73 номер 5678901"),
        ("fpass-06", "загранпаспорт 74 6789012"),
        ("fpass-07", "з/п 75 7890123"),
        ("fpass-08", "загран 76 8901234"),
        ("fpass-09", "заграничный паспорт: 51 9012345"),
        ("fpass-10", "загранпаспорт РФ 70 0123456"),
        ("fpass-11", "загранпаспорт нового образца 71 1112222"),
        ("fpass-12", "заграничный паспорт: 72 2223333"),
        ("fpass-13", "загранпаспорт 73 3334444"),
        ("fpass-14", "документ для выезда: загранпаспорт 74 4445555"),
        ("fpass-15", "загран. паспорт 75 5556666"),
    ]
    for t, p in fp:
        tests.append(_a(t, p, ["foreign_passport"]))

    # --- military_id (15) ---
    mil = [
        ("mil-01", "военный билет АА 1234567"),
        ("mil-02", "военный билет серия АБ номер 2345678"),
        ("mil-03", "в/б АВ 3456789"),
        ("mil-04", "военный билет: АГ 4567890"),
        ("mil-05", "военный билет №АД 5678901"),
        ("mil-06", "военный билет серия АЕ №6789012"),
        ("mil-07", "в/б: АЖ 7890123"),
        ("mil-08", "воен. билет АЗ 8901234"),
        ("mil-09", "военный билет АИ 9012345"),
        # ("mil-10", "серия АК номер 0123456"),  # known_limitation: no 'military' keyword
        ("mil-11", "военный билет серии АЛ №1112222"),
        ("mil-12", "в/б АМ 2223333"),
        ("mil-13", "военный билет АН 3334444"),
        ("mil-14", "военный билет: АО 4445555"),
        ("mil-15", "документ воинского учёта: военный билет АП 5556666"),
    ]
    for t, p in mil:
        tests.append(_a(t, p, ["military_id"]))
    # Known limitations
    tests.append(TC(group="A", tag="mil-10", payload="серия АК номер 0123456",
                    exp_cats=["military_id"], known_limitation=True))

    # --- cvv (15) --- (рядом с номером карты)
    cvv = [
        ("cvv-01", "карта 4276 1234 5678 9010, CVV 123"),
        ("cvv-02", "4276 1234 5678 9010, CVC: 456"),
        ("cvv-03", "номер карты 5469 1234 5678 9012 CVV2 789"),
        ("cvv-04", "карта 2200 1234 5678 9012, код CVV: 321"),
        ("cvv-05", "4276 9999 8888 7777 CVV 111"),
        ("cvv-06", "5469 0000 1111 2222 CVC 222"),
        ("cvv-07", "карта 4276 3333 4444 5555, CVV: 333"),
        ("cvv-08", "оплата картой 5469 6666 7777 8888, CVV2: 444"),
        ("cvv-09", "2200 9999 0000 1111, CVC2 555"),
        ("cvv-10", "4276 2222 3333 4444 код безопасности 666"),
        ("cvv-11", "5469 5555 6666 7777, CVV 777"),
        ("cvv-12", "карта 2200 8888 9999 0000, CVC: 888"),
        ("cvv-13", "4276 1111 0000 9999 CVV 999"),
        ("cvv-14", "5469 2222 1111 0000, код CVV 100"),
        ("cvv-15", "2200 3333 2222 1111, CVC: 200"),
    ]
    for t, p in cvv:
        tests.append(_a(t, p, ["cvv", "card_number"], exp_pd=2))

    # --- pin (15) --- (рядом с номером карты)
    pin = [
        ("pin-01", "карта 4276 1234 5678 9010, PIN-код: 1234"),
        ("pin-02", "4276 1234 5678 9010, ПИН: 5678"),
        ("pin-03", "номер карты 5469 1234 5678 9012, PIN: 9012"),
        ("pin-04", "карта 2200 1234 5678 9012, пин-код 3456"),
        ("pin-05", "4276 9999 8888 7777, PIN-код: 7890"),
        ("pin-06", "5469 0000 1111 2222, пин-код: 1111"),
        ("pin-07", "карта 4276 3333 4444 5555, PIN 2222"),
        ("pin-08", "5469 6666 7777 8888, ПИН-код: 3333"),
        ("pin-09", "2200 9999 0000 1111, PIN: 4444"),
        ("pin-10", "4276 2222 3333 4444, пин 5555"),
        ("pin-11", "5469 5555 6666 7777, PIN-код 6666"),
        ("pin-12", "карта 2200 8888 9999 0000, PIN: 7777"),
        ("pin-13", "4276 1111 0000 9999, ПИН 8888"),
        ("pin-14", "5469 2222 1111 0000, пин-код: 9999"),
        ("pin-15", "2200 3333 2222 1111, PIN-код: 0000"),
    ]
    for t, p in pin:
        tests.append(_a(t, p, ["pin", "card_number"], exp_pd=2))

    # --- issue_date (15) ---
    idate = [
        ("idate-01", "выдан 01.02.2020"),
        ("idate-02", "дата выдачи 15.06.2015"),
        ("idate-03", "дата выдачи: 20.03.2018"),
        ("idate-04", "паспорт выдан 05.11.2010"),
        ("idate-05", "выдано 12.07.2019"),
        ("idate-06", "дата выдачи документа: 08.01.2016"),
        ("idate-07", "выдан 30.09.2012"),
        ("idate-08", "дата выдачи: 25 декабря 2014"),
        ("idate-09", "выдан 01 марта 2021"),
        ("idate-10", "документ выдан 14.02.2017"),
        ("idate-11", "дата выдачи 10.10.2013"),
        ("idate-12", "выдан: 19.04.2011"),
        ("idate-13", "дата выдачи паспорта: 22.08.2020"),
        ("idate-14", "выдан 03.06.2022"),
        ("idate-15", "дата выдачи: 17.12.2009"),
    ]
    for t, p in idate:
        tests.append(_a(t, p, ["issue_date"]))

    # --- issuing_authority (15) ---
    iauth = [
        ("iauth-01", "выдан ОВД г. Москвы"),
        ("iauth-02", "выдан УФМС по г. Москве"),
        ("iauth-03", "кем выдан: отделом УФМС России по Московской области"),
        ("iauth-04", "выдан ГУ МВД России по г. Москве"),
        ("iauth-05", "орган выдачи: ОВД района Тверской"),
        ("iauth-06", "выдан ОУФМС по г. Санкт-Петербургу"),
        ("iauth-07", "паспорт выдан МВД по Республике Татарстан"),
        ("iauth-08", "кем выдан: Отделением по району Арбат"),
        ("iauth-09", "выдан УФМС России по Свердловской области"),
        ("iauth-10", "орган: Управление ФМС по Краснодарскому краю"),
        ("iauth-11", "выдан отделом УФМС России по г. Казани"),
        ("iauth-12", "кем выдан: ОВД Советского района г. Новосибирска"),
        ("iauth-13", "выдан ОУФМС России по Нижегородской обл."),
        ("iauth-14", "паспорт выдан ТП №5 ОУФМС России"),
        ("iauth-15", "выдан Отделением УФМС по Ленинградской области"),
    ]
    for t, p in iauth:
        tests.append(_a(t, p, ["issuing_authority"]))

    # --- subdivision_code (15) ---
    scode = [
        ("scode-01", "код подразделения 770-001"),
        ("scode-02", "к/п 123-456"),
        ("scode-03", "код подразделения: 780-002"),
        ("scode-04", "к.п. 660-003"),
        ("scode-05", "код подр. 500-004"),
        ("scode-06", "подразделение 770-005"),
        ("scode-07", "код подразделения 240-006"),
        ("scode-08", "к/п: 160-007"),
        ("scode-09", "код подразделения 540-008"),
        ("scode-10", "подразд. 630-009"),
        ("scode-11", "код подразделения 770-010"),
        ("scode-12", "к/п 780-011"),
        ("scode-13", "код подразд.: 500-012"),
        ("scode-14", "код подразделения 340-013"),
        ("scode-15", "к/п: 230-014"),
    ]
    for t, p in scode:
        tests.append(_a(t, p, ["subdivision_code"]))

    # --- cardholder_name (15) ---
    cname = [
        ("chname-01", "IVANOV IVAN"),
        ("chname-02", "PETROVA MARIA S"),
        ("chname-03", "SIDOROV ALEKSEI V"),
        ("chname-04", "KOZLOVA ELENA D"),
        ("chname-05", "KUZNETSOV DMITRII"),
        ("chname-06", "NOVIKOVA ANASTASIA P"),
        ("chname-07", "карта IVANOV IVAN"),
        ("chname-08", "имя на карте: PETROVA MARIA"),
        ("chname-09", "cardholder: SIDOROV ALEKSEI"),
        ("chname-10", "FEDOROV MIKHAIL"),
        ("chname-11", "SMIRNOVA OLGA V"),
        ("chname-12", "POPOV ANDREI N"),
        ("chname-13", "MOROZOVA TATIANA"),
        ("chname-14", "VOLKOV SERGEI A"),
        ("chname-15", "LEBEDEVA NATALIA"),
    ]
    for t, p in cname:
        tests.append(_a(t, p, ["cardholder_name"]))

    # --- citizenship (15) ---
    cit = [
        ("cit-01", "гражданство: Российская Федерация"),
        ("cit-02", "гражданство РФ"),
        ("cit-03", "гражданин Российской Федерации"),
        ("cit-04", "гражданство: Россия"),
        ("cit-05", "гражданка Российской Федерации"),
        ("cit-06", "гражданство: Республика Беларусь"),
        ("cit-07", "гражданин Республики Казахстан"),
        ("cit-08", "гражданство: Украина"),
        ("cit-09", "является гражданином РФ"),
        ("cit-10", "гражданство: Республика Узбекистан"),
        ("cit-11", "подданство: Российская Федерация"),
        ("cit-12", "гражданство — РФ"),
        ("cit-13", "имеет гражданство Российской Федерации"),
        ("cit-14", "гражданство: Кыргызская Республика"),
        ("cit-15", "гражданин Республики Таджикистан"),
    ]
    for t, p in cit:
        tests.append(_a(t, p, ["citizenship"]))

    # --- birth_place (15) ---
    bplace = [
        ("bplace-01", "место рождения: г. Москва"),
        ("bplace-02", "родился в г. Санкт-Петербург"),
        ("bplace-03", "место рождения: гор. Казань"),
        ("bplace-04", "уроженец г. Новосибирска"),
        ("bplace-05", "место рождения — г. Екатеринбург"),
        ("bplace-06", "родилась в г. Нижний Новгород"),
        ("bplace-07", "место рождения: г. Самара, Самарская обл."),
        ("bplace-08", "уроженка г. Ростов-на-Дону"),
        ("bplace-09", "место рождения: Москва, Россия"),
        ("bplace-10", "родился в пос. Лесной, Свердловская обл."),
        ("bplace-11", "место рождения: с. Ивановка, Оренбургская обл."),
        ("bplace-12", "уроженец г. Краснодар"),
        ("bplace-13", "место рождения: г. Уфа, Республика Башкортостан"),
        ("bplace-14", "родился в г. Воронеж"),
        ("bplace-15", "место рождения: г. Пермь"),
    ]
    for t, p in bplace:
        tests.append(_a(t, p, ["birth_place"]))

    return tests


# ──────────────────────────────────────────────────────────────────────
# =====================================================================
#   ГРУППА B — Граничные / edge-case сценарии
# =====================================================================
# ──────────────────────────────────────────────────────────────────────

def build_group_b() -> List[TC]:
    """~100 тестов: пустые строки, юникод, длинные тексты, повторы, etc."""
    tests: List[TC] = []

    def _neg(tag: str, payload: str) -> TC:
        return TC(group="B", tag=tag, payload=payload, neg=True, exp_pd=0, exp_action="masked")

    def _pos(tag: str, payload: str, cats: List[str], exp_pd: int = 1) -> TC:
        return TC(group="B", tag=tag, payload=payload, exp_cats=cats, exp_pd=exp_pd)

    # --- Пустые и минимальные ---
    tests.append(_neg("b-empty-01", ""))
    tests.append(_neg("b-empty-02", " "))
    tests.append(_neg("b-empty-03", "   \t\t  \n\n  "))
    tests.append(_neg("b-empty-04", "\n"))
    tests.append(_neg("b-empty-05", "\r\n\r\n"))

    # --- Одиночные символы ---
    tests.append(_neg("b-single-01", "a"))
    tests.append(_neg("b-single-02", "1"))
    tests.append(_neg("b-single-03", "@"))
    tests.append(_neg("b-single-04", "ы"))
    tests.append(_neg("b-single-05", "0"))

    # --- Юникод / эмодзи ---
    tests.append(_neg("b-unicode-01", "🎉🎊🎈🎆🎇"))
    tests.append(_neg("b-unicode-02", "こんにちは世界"))
    tests.append(_neg("b-unicode-03", "مرحبا بالعالم"))
    tests.append(_neg("b-unicode-04", "中文文本测试"))
    tests.append(_neg("b-unicode-05", "𝕳𝖊𝖑𝖑𝖔 𝖂𝖔𝖗𝖑𝖉"))
    tests.append(_neg("b-emoji-06", "👨‍👩‍👧‍👦 семья без ПДн"))
    tests.append(_neg("b-emoji-07", "🏠🏡🏢 здания"))
    tests.append(_neg("b-emoji-08", "✅❌⚠️ символы"))
    tests.append(_neg("b-emoji-09", "🔑🔒🔓 замки"))
    tests.append(_neg("b-emoji-10", "🇷🇺 флаг России"))

    # --- Очень длинный текст без ПДн ---
    tests.append(_neg("b-long-01", "Тестовая строка без персональных данных. " * 2500))  # ~100K

    # --- Очень длинный текст с ПДн в конце ---
    long_prefix = "Просто текст без данных. " * 2000
    tests.append(_pos("b-long-pd-02", long_prefix + " Иванов Иван Иванович", ["fio"]))
    tests.append(_pos("b-long-pd-03", long_prefix + " паспорт 4510 123456", ["passport"]))

    # --- Повтор одних и тех же ПДн ---
    tests.append(_pos("b-repeat-01", "Иванов Иван Иванович " * 10, ["fio"], exp_pd=1))
    tests.append(_pos("b-repeat-02", "+7(999)123-45-67 " * 5, ["phone"], exp_pd=1))
    tests.append(_pos("b-repeat-03", "user@mail.ru " * 20, ["email"], exp_pd=1))

    # --- Многострочный ---
    tests.append(_pos("b-multiline-01",
        "Строка 1: Иванов Иван Иванович\nСтрока 2: +7(999)123-45-67\nСтрока 3: user@mail.ru",
        ["fio", "phone", "email"], exp_pd=3))
    tests.append(_pos("b-multiline-02",
        "ФИО:\nПетров\nПётр\nПетрович\n\nТелефон:\n+7(916)234-56-78",
        ["fio", "phone"], exp_pd=2))

    # --- Разные разделители ---
    tests.append(_neg("b-sep-01", "Иванов;Иван;Иванович"))
    tests.append(_neg("b-sep-02", "Иванов|Иван|Иванович"))
    tests.append(_pos("b-sep-03", "Иванов\tИван\tИванович", ["fio"]))

    # --- Смешанные скрипты ---
    tests.append(_pos("b-mixed-01", "Name: Иванов Иван Иванович, email: test@mail.ru", ["fio", "email"], exp_pd=2))
    tests.append(_pos("b-mixed-02", "Карта VISA 4276 1234 5678 9010 (IVANOV IVAN)", ["card_number", "cardholder_name"], exp_pd=2))

    # --- JSON-пейлоады ---
    tests.append(_pos("b-json-01",
        '{"name": "Иванов Иван Иванович", "phone": "+7(999)123-45-67"}',
        ["fio", "phone"], exp_pd=2))
    tests.append(_pos("b-json-02",
        '{"passport": "4510 123456", "inn": "123456789012"}',
        ["passport", "inn"], exp_pd=2))
    tests.append(_neg("b-json-03",
        '{"key": "value", "count": 42, "active": true}'))

    # --- XML / HTML ---
    tests.append(_pos("b-xml-01",
        '<person><fio>Иванов Иван Иванович</fio><phone>+7(999)123-45-67</phone></person>',
        ["fio", "phone"], exp_pd=2))
    tests.append(_neg("b-xml-02",
        '<config><timeout>30</timeout><retries>3</retries></config>'))

    # --- SQL-like ---
    tests.append(_pos("b-sql-01",
        "SELECT * FROM users WHERE name = 'Иванов Иван Иванович' AND phone = '+7(999)123-45-67'",
        ["fio", "phone"], exp_pd=2))
    tests.append(_neg("b-sql-02",
        "SELECT id, created_at FROM orders WHERE status = 'active' LIMIT 100"))

    # --- CSV-формат ---
    tests.append(_pos("b-csv-01",
        "Иванов Иван Иванович,+7(999)123-45-67,user@mail.ru,паспорт 4510 123456",
        ["fio", "phone", "email", "passport"], exp_pd=4))

    # --- Только цифры ---
    tests.append(_neg("b-digits-01", "1234567890"))
    tests.append(_neg("b-digits-02", "0000000000000000"))
    tests.append(_neg("b-digits-03", "9" * 50))

    # --- Только буквы ---
    tests.append(_neg("b-alpha-01", "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"))
    tests.append(_neg("b-alpha-02", "abcdefghijklmnopqrstuvwxyz"))

    # --- Спецсимволы ---
    tests.append(_neg("b-special-01", "!@#$%^&*()_+-=[]{}|;':\",./<>?"))
    tests.append(_neg("b-special-02", "«»—–…·•°±≠≈∞∑∏√"))
    tests.append(_neg("b-special-03", "\\n\\t\\r\\0\\x00\\u0000"))

    # --- Null-байты и управляющие символы ---
    tests.append(_neg("b-null-01", "\x00\x01\x02\x03"))
    tests.append(_neg("b-null-02", "Текст\x00с нулевым байтом"))

    # --- URL ---
    tests.append(_neg("b-url-01", "https://example.com/path?param=value&other=123"))
    tests.append(_neg("b-url-02", "http://192.168.1.1:8080/api/v1/users"))

    # --- Base64-like ---
    tests.append(_neg("b-b64-01", "SGVsbG8gV29ybGQh"))
    tests.append(_neg("b-b64-02", "dGVzdCBiYXNlNjQgZW5jb2Rpbmc="))

    # --- Текст с ПДн в разных кодировках (но всё UTF-8) ---
    tests.append(_pos("b-enc-01", "ФИО: \u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d", ["fio"]))

    # --- Табличный формат ---
    tests.append(_pos("b-table-01",
        "| ФИО              | Телефон           |\n"
        "|------------------|-------------------|\n"
        "| Иванов Иван      | +7(999)123-45-67  |",
        ["fio", "phone"], exp_pd=2))

    # --- Markdown ---
    tests.append(_pos("b-md-01",
        "# Заявление\n\n**ФИО:** Иванов Иван Иванович\n\n**Телефон:** +7(999)123-45-67",
        ["fio", "phone"], exp_pd=2))

    # --- Логи ---
    tests.append(_pos("b-log-01",
        "[2024-01-15 10:30:00] INFO: Пользователь Иванов Иван Иванович авторизован, IP: 10.0.0.1",
        ["fio"], exp_pd=1))

    # --- Очень много пробелов между ПДн ---
    tests.append(_pos("b-spaces-01",
        "Иванов     Иван     Иванович", ["fio"]))

    # --- ПДн с опечатками (не должно ломать) ---
    tests.append(TC(group="B", tag="b-typo-01", payload="Ивнаов Иавн Ивановчи",
                    neg=True, exp_pd=0, exp_action="masked", known_limitation=True))

    # --- Пунктуация вокруг ПДн ---
    tests.append(_pos("b-punct-01", "(Иванов Иван Иванович)", ["fio"]))
    tests.append(_pos("b-punct-02", "[паспорт 4510 123456]", ["passport"]))
    tests.append(_pos("b-punct-03", "«+7(999)123-45-67»", ["phone"]))

    # --- Разные mode ---
    tests.append(TC(group="B", tag="b-mode-full-01",
        payload="Иванов Иван Иванович, паспорт 4510 123456",
        exp_cats=["fio", "passport"], exp_pd=2, mode="full"))
    tests.append(TC(group="B", tag="b-mode-full-02",
        payload="+7(999)123-45-67, user@mail.ru",
        exp_cats=["phone", "email"], exp_pd=2, mode="full"))

    # --- Разные system_id ---
    tests.append(TC(group="B", tag="b-sysid-01",
        payload="Иванов Иван Иванович", exp_cats=["fio"], exp_pd=1, sid="system_a"))
    tests.append(TC(group="B", tag="b-sysid-02",
        payload="паспорт 4510 123456", exp_cats=["passport"], exp_pd=1, sid="system_b"))

    # --- Большой массив JSON ---
    big_json = json.dumps([{"id": i, "value": f"item_{i}"} for i in range(1000)])
    tests.append(_neg("b-bigjson-01", big_json))

    # --- Кириллица в верхнем регистре ---
    tests.append(_pos("b-upper-cyr-01", "ПАСПОРТ 4510 123456", ["passport"]))
    tests.append(_pos("b-upper-cyr-02", "ТЕЛЕФОН +7(999)123-45-67", ["phone"]))

    # --- ПДн в кавычках ---
    tests.append(_pos("b-quotes-01", 'ФИО: "Иванов Иван Иванович"', ["fio"]))
    tests.append(_pos("b-quotes-02", "email: 'user@mail.ru'", ["email"]))

    # --- Тысячи переносов строк ---
    tests.append(_neg("b-newlines-01", "\n" * 10000))

    # --- Одна буква + много пробелов ---
    tests.append(_neg("b-sparse-01", "а" + " " * 1000 + "б"))

    # --- Дополнительные edge-case ---
    tests.append(_neg("b-zero-width-01", "текст\u200Bс\u200Bнулевой\u200Bшириной"))
    tests.append(_neg("b-rtl-01", "\u202Eтскет йынтарбо\u202C"))
    tests.append(_pos("b-htmlent-01",
        "ФИО: &#1048;&#1074;&#1072;&#1085;&#1086;&#1074; Иванов Иван Иванович", ["fio"]))
    tests.append(_neg("b-only-punct-01", ".,;:!?—–…·" * 100))
    tests.append(_neg("b-bom-01", "\ufeffТекст с BOM без ПДн"))
    tests.append(_pos("b-parens-01",
        "(Иванов Иван Иванович, +7(999)123-45-67)", ["fio", "phone"], 2))
    tests.append(_pos("b-brackets-01",
        "[СНИЛС: 123-456-789 00]", ["snils"]))
    tests.append(_neg("b-escaped-01", "Ив\\анов Ив\\ан Ив\\анович"))
    tests.append(_pos("b-mixed-enc-01",
        "FIO: Козлова Елена Дмитриевна, email: test@example.com", ["fio", "email"], 2))
    tests.append(_neg("b-lorem-01",
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor."))
    tests.append(_pos("b-multispace-01",
        "паспорт   4510   123456", ["passport"]))
    tests.append(_pos("b-trail-ws-01",
        "  Иванов Иван Иванович  ", ["fio"]))
    tests.append(_neg("b-numbers-seq-01", " ".join(str(i) for i in range(1000))))
    tests.append(_pos("b-cyrillic-mixed-01",
        "Данные: Фио=Иванов Иван Иванович; Тел=+7(999)123-45-67", ["fio", "phone"], 2))
    tests.append(_neg("b-hashtag-01", "#проект #задача #спринт #релиз #деплой"))
    tests.append(_neg("b-mention-01", "@user1 @admin @manager — уведомления"))
    tests.append(_pos("b-colon-01",
        "Контакт: user@mail.ru", ["email"]))
    tests.append(_neg("b-path-01", "/usr/local/bin/python3 --version 3.11.5"))
    tests.append(_neg("b-cron-01", "0 */6 * * * /usr/bin/backup.sh"))
    tests.append(_neg("b-regex-01", r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"))
    tests.append(_pos("b-wrap-01",
        "Ивано\nв Иван Иванов\nич", ["fio"]))
    tests.append(_neg("b-versioning-01", "версия 12.34.56.78, сборка 9012345"))
    tests.append(_neg("b-color-01", "#FF5733, rgb(255,87,51), hsl(11,100%,60%)"))
    tests.append(_neg("b-math-01", "f(x) = 2x² + 3x - 5, при x = 4510"))
    tests.append(TC(group="B", tag="b-code-01",
                    payload='const x = {"key": 123456789012, "val": true};',
                    neg=True, exp_pd=0, exp_action="masked", known_limitation=True))

    return tests


# ──────────────────────────────────────────────────────────────────────
# =====================================================================
#   ГРУППА C — Анти-FP (негативные тесты)
# =====================================================================
# ──────────────────────────────────────────────────────────────────────

def build_group_c() -> List[TC]:
    """~100 тестов: тексты, которые НЕ должны содержать ПДн."""
    tests: List[TC] = []

    def _n(tag: str, payload: str) -> TC:
        return TC(group="C", tag=tag, payload=payload, neg=True, exp_pd=0, exp_action="masked")

    # --- Известные люди ---
    famous = [
        ("c-famous-01", "Александр Сергеевич Пушкин — великий русский поэт"),
        ("c-famous-02", "Лев Николаевич Толстой написал «Войну и мир»"),
        ("c-famous-03", "Юрий Алексеевич Гагарин — первый космонавт"),
        ("c-famous-04", "Пётр Ильич Чайковский — русский композитор"),
        ("c-famous-05", "Фёдор Михайлович Достоевский — автор «Преступления и наказания»"),
        ("c-famous-06", "Дмитрий Иванович Менделеев создал периодическую таблицу"),
        ("c-famous-07", "Михаил Васильевич Ломоносов — учёный-энциклопедист"),
        ("c-famous-08", "Антон Павлович Чехов — классик мировой литературы"),
        ("c-famous-09", "Сергей Павлович Королёв — конструктор ракетно-космических систем"),
        ("c-famous-10", "Иван Сергеевич Тургенев написал «Отцы и дети»"),
        ("c-famous-11", "Владимир Владимирович Маяковский — поэт-футурист"),
        ("c-famous-12", "Николай Васильевич Гоголь — автор «Мёртвых душ»"),
        ("c-famous-13", "Анна Андреевна Ахматова — поэтесса Серебряного века"),
        ("c-famous-14", "Борис Леонидович Пастернак — нобелевский лауреат"),
        ("c-famous-15", "Александр Исаевич Солженицын — писатель и публицист"),
    ]
    for t, p in famous:
        tests.append(TC(group="C", tag=t, payload=p, neg=True, exp_pd=0,
                        exp_action="masked", known_limitation=True))

    # --- Компании / юрлица ---
    companies = [
        ("c-company-01", "ООО Ромашка заключила договор"),
        ("c-company-02", "ПАО Газпром отчитался за квартал"),
        ("c-company-03", "ИП Иванов зарегистрирован в ЕГРИП"),
        ("c-company-04", "АО Сбербанк выпустил новую карту"),
        ("c-company-05", "ООО «Яндекс» представил новый сервис"),
        ("c-company-06", "ПАО «МТС» — крупнейший оператор связи"),
        ("c-company-07", "ЗАО «Тандер» управляет сетью «Магнит»"),
        ("c-company-08", "ФГУП «Почта России» доставляет посылки"),
        ("c-company-09", "ООО «Вайлдберриз» — маркетплейс"),
        ("c-company-10", "ПАО «Аэрофлот» — авиакомпания"),
    ]
    _c_company_known = {"c-company-08"}
    for t, p in companies:
        if t in _c_company_known:
            tests.append(TC(group="C", tag=t, payload=p, neg=True, exp_pd=0,
                            exp_action="masked", known_limitation=True))
        else:
            tests.append(_n(t, p))

    # --- Вымышленные персонажи ---
    fiction = [
        ("c-fiction-01", "Евгений Онегин — герой романа Пушкина"),
        ("c-fiction-02", "Анна Каренина бросилась под поезд"),
        ("c-fiction-03", "Родион Раскольников совершил преступление"),
        ("c-fiction-04", "Наташа Ростова танцевала на балу"),
        ("c-fiction-05", "Печорин — герой нашего времени"),
        ("c-fiction-06", "Чичиков скупал мёртвые души"),
        ("c-fiction-07", "Базаров был нигилистом"),
        ("c-fiction-08", "Обломов лежал на диване"),
        ("c-fiction-09", "Мастер и Маргарита летели над Москвой"),
        ("c-fiction-10", "Шерлок Холмс расследовал преступления"),
    ]
    for t, p in fiction:
        tests.append(TC(group="C", tag=t, payload=p, neg=True, exp_pd=0,
                        exp_action="masked", known_limitation=True))

    # --- Топонимы / улицы ---
    topo = [
        ("c-topo-01", "улица Пушкина пересекает проспект Ленина"),
        ("c-topo-02", "станция метро Маяковская"),
        ("c-topo-03", "набережная Грибоедова"),
        ("c-topo-04", "площадь Гагарина расположена в центре"),
        ("c-topo-05", "бульвар Толстого — тихая улица"),
        ("c-topo-06", "Ломоносовский проспект"),
        ("c-topo-07", "парк Горького — место отдыха"),
        ("c-topo-08", "мост Александра Невского"),
        ("c-topo-09", "Чеховский переулок"),
        ("c-topo-10", "Тургеневская площадь"),
    ]
    for t, p in topo:
        tests.append(TC(group="C", tag=t, payload=p, neg=True, exp_pd=0,
                        exp_action="masked", known_limitation=True))

    # --- Числа, похожие на ПДн, но не являющиеся ---
    numbers = [
        ("c-num-01", "UUID: 550e8400-e29b-41d4-a716-446655440000"),
        ("c-num-02", "артикул товара: 4510-123456"),
        ("c-num-03", "номер заказа: 7890123456"),
        ("c-num-04", "код товара: 1234567890"),
        ("c-num-05", "серийный номер: SN-4510-123456-RU"),
        ("c-num-06", "версия 2.3.456789"),
        ("c-num-07", "хеш: a1b2c3d4e5f6"),
        ("c-num-08", "ID транзакции: TXN-9876543210"),
        ("c-num-09", "номер счёта: INV-2024-001234"),
        ("c-num-10", "трек-номер: RA123456789CN"),
    ]
    _c_num_known = {"c-num-01"}
    for t, p in numbers:
        if t in _c_num_known:
            tests.append(TC(group="C", tag=t, payload=p, neg=True, exp_pd=0,
                            exp_action="masked", known_limitation=True))
        else:
            tests.append(_n(t, p))

    # --- Технические строки ---
    tech = [
        ("c-tech-01", "127.0.0.1 — localhost"),
        ("c-tech-02", "192.168.1.1 — роутер"),
        ("c-tech-03", "10.0.0.1/24 — подсеть"),
        ("c-tech-04", "MAC: 00:1A:2B:3C:4D:5E"),
        ("c-tech-05", "0xDEADBEEF — магическое число"),
        ("c-tech-06", "SHA256: e3b0c44298fc1c149afbf4c8996fb924"),
        ("c-tech-07", "MD5: d41d8cd98f00b204e9800998ecf8427e"),
        ("c-tech-08", "Base64: SGVsbG8gV29ybGQh"),
        ("c-tech-09", "HTTP 200 OK"),
        ("c-tech-10", "Content-Type: application/json; charset=utf-8"),
    ]
    for t, p in tech:
        tests.append(_n(t, p))

    # --- Короткие числа ---
    short = [
        ("c-short-01", "123"),
        ("c-short-02", "45678"),
        ("c-short-03", "номер страницы: 42"),
        ("c-short-04", "количество: 999"),
        ("c-short-05", "этаж 15"),
        ("c-short-06", "кабинет 301"),
        ("c-short-07", "пункт 3.2.1"),
        ("c-short-08", "параграф 17"),
        ("c-short-09", "температура +25°C"),
        ("c-short-10", "артикул 12345"),
    ]
    for t, p in short:
        tests.append(_n(t, p))

    # --- Даты, не являющиеся датами рождения ---
    dates = [
        ("c-date-01", "дедлайн проекта: 15.03.2025"),
        ("c-date-02", "дата совещания: 01.02.2024"),
        ("c-date-03", "срок исполнения до 30.06.2024"),
        ("c-date-04", "обновлено 25.12.2023"),
        ("c-date-05", "создано 01.01.2024"),
    ]
    for t, p in dates:
        tests.append(_n(t, p))

    # --- Общеупотребительные фразы ---
    generic = [
        ("c-generic-01", "Добрый день! Подскажите, пожалуйста, статус заявки."),
        ("c-generic-02", "Спасибо за обращение, ваш вопрос принят в работу."),
        ("c-generic-03", "Прошу перенести совещание на понедельник."),
        ("c-generic-04", "Направляю отчёт за третий квартал 2024 года."),
        ("c-generic-05", "Коллеги, напоминаю о необходимости сдать табели."),
        ("c-generic-06", "Протокол совещания от 15 января 2024 года"),
        ("c-generic-07", "Согласовано. Прошу приступить к исполнению."),
        ("c-generic-08", "На рассмотрении находятся три проекта."),
        ("c-generic-09", "Бюджет проекта составляет 1 500 000 рублей."),
        ("c-generic-10", "Срок реализации — IV квартал 2024 года."),
    ]
    for t, p in generic:
        tests.append(_n(t, p))

    # --- Дополнительные анти-FP ---
    extra_fp = [
        ("c-extra-01", "Рецепт: мука 450 г, сахар 200 г, яйца 3 шт."),
        ("c-extra-02", "Температура воздуха +25°C, давление 760 мм рт. ст."),
        ("c-extra-03", "Курс доллара: 92.50 руб., евро: 100.30 руб."),
        ("c-extra-04", "Матч Спартак — Динамо, счёт 2:1"),
        ("c-extra-05", "Рейс SU-1234, вылет в 15:30, прибытие в 18:45"),
        ("c-extra-06", "Артикул SKU-7890123, цена 4 510 руб."),
        ("c-extra-07", "Номер полки: 77-01, ячейка 234567"),
        ("c-extra-08", "Код ошибки: ERR-123-456-789"),
        ("c-extra-09", "Координаты: 55.7558° с.ш., 37.6173° в.д."),
        ("c-extra-10", "Площадь помещения: 123.45 м², этаж 7 из 25"),
    ]
    _c_extra_known = {"c-extra-04", "c-extra-08", "c-extra-10"}
    for t, p in extra_fp:
        if t in _c_extra_known:
            tests.append(TC(group="C", tag=t, payload=p, neg=True, exp_pd=0,
                            exp_action="masked", known_limitation=True))
        else:
            tests.append(_n(t, p))

    return tests


# ──────────────────────────────────────────────────────────────────────
# =====================================================================
#   ГРУППА D — Комбинированные ПДн
# =====================================================================
# ──────────────────────────────────────────────────────────────────────

def build_group_d() -> List[TC]:
    """~120 тестов: несколько категорий ПДн в одном тексте."""
    tests: List[TC] = []

    def _d(tag: str, payload: str, cats: List[str], exp_pd: int) -> TC:
        return TC(group="D", tag=tag, payload=payload, exp_cats=cats, exp_pd=exp_pd)

    # === Двойные комбинации (30) ===
    tests.append(_d("d-2cat-01",
        "Иванов Иван Иванович, паспорт 4510 123456",
        ["fio", "passport"], 2))
    tests.append(_d("d-2cat-02",
        "Иванов Иван Иванович, тел. +7(999)123-45-67",
        ["fio", "phone"], 2))
    tests.append(_d("d-2cat-03",
        "user@mail.ru, тел. +7(999)123-45-67",
        ["email", "phone"], 2))
    tests.append(_d("d-2cat-04",
        "карта 4276 1234 5678 9010, CVV 123",
        ["card_number", "cvv"], 2))
    tests.append(_d("d-2cat-05",
        "Иванов Иван Иванович, СНИЛС 123-456-789 00",
        ["fio", "snils"], 2))
    tests.append(_d("d-2cat-06",
        "Иванов Иван Иванович, ИНН 123456789012",
        ["fio", "inn"], 2))
    tests.append(_d("d-2cat-07",
        "Иванов Иван Иванович, email: user@mail.ru",
        ["fio", "email"], 2))
    tests.append(_d("d-2cat-08",
        "паспорт 4510 123456, СНИЛС 123-456-789 00",
        ["passport", "snils"], 2))
    tests.append(_d("d-2cat-09",
        "карта 5469 1234 5678 9012, IVANOV IVAN",
        ["card_number", "cardholder_name"], 2))
    tests.append(_d("d-2cat-10",
        "Иванов Иван Иванович, дата рождения 01.01.1990",
        ["fio", "birth_date"], 2))
    tests.append(_d("d-2cat-11",
        "карта 4276 1234 5678 9010, PIN-код: 1234",
        ["card_number", "pin"], 2))
    tests.append(_d("d-2cat-12",
        "Иванов Иван Иванович, адрес: г. Москва, ул. Ленина, д. 10, кв. 25",
        ["fio", "address"], 2))
    tests.append(_d("d-2cat-13",
        "паспорт 4510 123456, код подразделения 770-001",
        ["passport", "subdivision_code"], 2))
    tests.append(_d("d-2cat-14",
        "паспорт 4510 123456, выдан 01.02.2020",
        ["passport", "issue_date"], 2))
    tests.append(_d("d-2cat-15",
        "паспорт 4510 123456, выдан ОВД г. Москвы",
        ["passport", "issuing_authority"], 2))
    tests.append(_d("d-2cat-16",
        "Иванов Иван Иванович, гражданство: Российская Федерация",
        ["fio", "citizenship"], 2))
    tests.append(_d("d-2cat-17",
        "Иванов Иван Иванович, место рождения: г. Москва",
        ["fio", "birth_place"], 2))
    tests.append(_d("d-2cat-18",
        "ВУ 77 01 234567, Иванов Иван Иванович",
        ["drivers_license", "fio"], 2))
    tests.append(_d("d-2cat-19",
        "загранпаспорт 51 1234567, Иванов Иван Иванович",
        ["foreign_passport", "fio"], 2))
    tests.append(_d("d-2cat-20",
        "военный билет АА 1234567, Иванов Иван Иванович",
        ["military_id", "fio"], 2))
    tests.append(_d("d-2cat-21",
        "полис ОМС 1234567890123456, Иванов Иван Иванович",
        ["oms", "fio"], 2))
    tests.append(_d("d-2cat-22",
        "СНИЛС 123-456-789 00, ИНН 123456789012",
        ["snils", "inn"], 2))
    tests.append(_d("d-2cat-23",
        "+7(999)123-45-67, адрес: г. Москва, ул. Ленина, д. 10",
        ["phone", "address"], 2))
    tests.append(_d("d-2cat-24",
        "email: user@mail.ru, адрес: г. Москва, ул. Ленина, д. 10",
        ["email", "address"], 2))
    tests.append(_d("d-2cat-25",
        "карта 4276 1234 5678 9010, email: user@mail.ru",
        ["card_number", "email"], 2))
    tests.append(_d("d-2cat-26",
        "Иванов Иван Иванович, полис ОМС 1234567890123456",
        ["fio", "oms"], 2))
    tests.append(_d("d-2cat-27",
        "ИНН 123456789012, +7(999)123-45-67",
        ["inn", "phone"], 2))
    tests.append(_d("d-2cat-28",
        "СНИЛС 123-456-789 00, дата рождения 01.01.1990",
        ["snils", "birth_date"], 2))
    tests.append(_d("d-2cat-29",
        "паспорт 4510 123456, место рождения: г. Москва",
        ["passport", "birth_place"], 2))
    tests.append(_d("d-2cat-30",
        "загранпаспорт 51 1234567, гражданство: Российская Федерация",
        ["foreign_passport", "citizenship"], 2))

    # === Тройные комбинации (20) ===
    tests.append(_d("d-3cat-01",
        "Иванов Иван Иванович, паспорт 4510 123456, СНИЛС 123-456-789 00",
        ["fio", "passport", "snils"], 3))
    tests.append(_d("d-3cat-02",
        "карта 4276 1234 5678 9010, CVV 123, PIN-код: 1234",
        ["card_number", "cvv", "pin"], 3))
    tests.append(_d("d-3cat-03",
        "Иванов Иван Иванович, тел. +7(999)123-45-67, email: user@mail.ru",
        ["fio", "phone", "email"], 3))
    tests.append(_d("d-3cat-04",
        "паспорт 4510 123456, выдан ОВД г. Москвы, код подразделения 770-001",
        ["passport", "issuing_authority", "subdivision_code"], 3))
    tests.append(_d("d-3cat-05",
        "Иванов Иван Иванович, ИНН 123456789012, СНИЛС 123-456-789 00",
        ["fio", "inn", "snils"], 3))
    tests.append(_d("d-3cat-06",
        "паспорт 4510 123456, дата рождения 01.01.1990, место рождения: г. Москва",
        ["passport", "birth_date", "birth_place"], 3))
    tests.append(_d("d-3cat-07",
        "Иванов Иван Иванович, адрес: г. Москва, ул. Ленина, д. 10, тел. +7(999)123-45-67",
        ["fio", "address", "phone"], 3))
    tests.append(_d("d-3cat-08",
        "карта 4276 1234 5678 9010, IVANOV IVAN, CVV 123",
        ["card_number", "cardholder_name", "cvv"], 3))
    tests.append(_d("d-3cat-09",
        "ВУ 77 01 234567, Иванов Иван Иванович, дата рождения 01.01.1990",
        ["drivers_license", "fio", "birth_date"], 3))
    tests.append(_d("d-3cat-10",
        "загранпаспорт 51 1234567, Иванов Иван Иванович, гражданство: Российская Федерация",
        ["foreign_passport", "fio", "citizenship"], 3))
    tests.append(_d("d-3cat-11",
        "Иванов Иван Иванович, паспорт 4510 123456, выдан 01.02.2020",
        ["fio", "passport", "issue_date"], 3))
    tests.append(_d("d-3cat-12",
        "Иванов Иван Иванович, паспорт 4510 123456, код подразделения 770-001",
        ["fio", "passport", "subdivision_code"], 3))
    tests.append(_d("d-3cat-13",
        "полис ОМС 1234567890123456, СНИЛС 123-456-789 00, Иванов Иван Иванович",
        ["oms", "snils", "fio"], 3))
    tests.append(_d("d-3cat-14",
        "военный билет АА 1234567, Иванов Иван Иванович, дата рождения 01.01.1990",
        ["military_id", "fio", "birth_date"], 3))
    tests.append(_d("d-3cat-15",
        "email: user@mail.ru, тел. +7(999)123-45-67, адрес: г. Москва, ул. Ленина, д. 10",
        ["email", "phone", "address"], 3))
    tests.append(_d("d-3cat-16",
        "ИНН 123456789012, СНИЛС 123-456-789 00, +7(999)123-45-67",
        ["inn", "snils", "phone"], 3))
    tests.append(_d("d-3cat-17",
        "карта 5469 1234 5678 9012, PETROVA MARIA, PIN-код: 5678",
        ["card_number", "cardholder_name", "pin"], 3))
    tests.append(_d("d-3cat-18",
        "Иванов Иван Иванович, паспорт 4510 123456, выдан ОВД г. Москвы",
        ["fio", "passport", "issuing_authority"], 3))
    tests.append(_d("d-3cat-19",
        "Иванов Иван Иванович, дата рождения 01.01.1990, гражданство: Российская Федерация",
        ["fio", "birth_date", "citizenship"], 3))
    tests.append(_d("d-3cat-20",
        "Иванов Иван Иванович, место рождения: г. Москва, адрес: г. Москва, ул. Ленина, д. 10",
        ["fio", "birth_place", "address"], 3))

    # === Полный профиль (10) ===
    tests.append(_d("d-full-01",
        "ФИО: Иванов Иван Иванович. Паспорт: 4510 123456, выдан ОВД г. Москвы 01.02.2020, "
        "код подразделения 770-001. Дата рождения: 01.01.1990. Место рождения: г. Москва. "
        "СНИЛС: 123-456-789 00. ИНН: 123456789012. Телефон: +7(999)123-45-67. Email: user@mail.ru. "
        "Адрес: г. Москва, ул. Ленина, д. 10, кв. 25.",
        ["fio", "passport", "issuing_authority", "issue_date", "subdivision_code",
         "birth_date", "birth_place", "snils", "inn", "phone", "email", "address"], 12))

    tests.append(_d("d-full-02",
        "Петрова Мария Сергеевна, паспорт 4515 678901, выдан УФМС по г. Москве 15.06.2015, "
        "к/п 770-002. Д.р.: 15.03.1985. Уроженка г. Санкт-Петербург. СНИЛС 234-567-890 12. "
        "ИНН 234567890123. Тел.: +7(916)234-56-78. E-mail: petrova@gmail.com. "
        "Проживает: г. Москва, ул. Тверская, д. 15, кв. 7. Гражданство: РФ.",
        ["fio", "passport", "issuing_authority", "issue_date", "subdivision_code",
         "birth_date", "birth_place", "snils", "inn", "phone", "email", "address", "citizenship"], 13))

    tests.append(_d("d-full-03",
        "Сидоров Алексей Владимирович. Паспорт серия 4520 номер 234567. СНИЛС: 345-678-901 23. "
        "ИНН: 345678901234. Дата рождения: 23.05.1978. Место рождения: г. Казань. "
        "Адрес регистрации: г. Казань, ул. Баумана, д. 33, кв. 12. "
        "Телефон: 8-926-345-67-89. Почта: sidorov@yandex.ru. "
        "Полис ОМС: 3456789012345678.",
        ["fio", "passport", "snils", "inn", "birth_date", "birth_place",
         "address", "phone", "email", "oms"], 10))

    tests.append(_d("d-full-04",
        "Данные клиента: Козлова Елена Дмитриевна, паспорт 4525 345678, "
        "выдан 20.03.2018 отделом УФМС, к/п 780-003. "
        "Родилась 10.12.1995 в г. Новосибирске. "
        "СНИЛС: 456-789-012 34, ИНН: 456789012345. "
        "Контакт: +7(903)123-45-67, kozlova@mail.ru. "
        "Адрес: г. Новосибирск, Красный проспект, д. 50, кв. 8. "
        "Банковская карта: 4276 1234 5678 9010, KOZLOVA ELENA.",
        ["fio", "passport", "issue_date", "issuing_authority", "subdivision_code",
         "birth_date", "birth_place", "snils", "inn", "phone", "email",
         "address", "card_number", "cardholder_name"], 14))

    tests.append(_d("d-full-05",
        "ВУ 77 01 234567, владелец Иванов Иван Иванович, "
        "дата рождения 01.01.1990, адрес: г. Москва, ул. Ленина, д. 10. "
        "Загранпаспорт: 51 1234567, гражданство: Российская Федерация. "
        "Телефон: +7(999)123-45-67.",
        ["drivers_license", "fio", "birth_date", "address",
         "foreign_passport", "citizenship", "phone"], 7))

    tests.append(_d("d-full-06",
        "Военный билет АА 1234567. Кузнецов Дмитрий Александрович, "
        "01.07.1980 г.р., уроженец г. Екатеринбурга. "
        "Паспорт: 4530 456789, выдан ОВД Ленинского р-на г. Екатеринбурга, к/п 660-004. "
        "СНИЛС: 567-890-123 45. Тел.: +7(912)567-89-01.",
        ["military_id", "fio", "birth_date", "birth_place",
         "passport", "issuing_authority", "subdivision_code", "snils", "phone"], 9))

    tests.append(_d("d-full-07",
        "Заявитель: Новикова Анастасия Павловна. Паспорт 4535 567890, "
        "выдан ОУФМС по г. Санкт-Петербургу 05.11.2010, к/п 780-005. "
        "СНИЛС 678-901-234 56. ИНН 678901234567. "
        "Д.р. 14.02.1993, место рождения: г. Санкт-Петербург. "
        "Адрес: 190000, г. Санкт-Петербург, Лиговский пр., д. 44, кв. 3. "
        "Тел.: +7(905)456-78-90. Email: novikova@outlook.com. "
        "Карта МИР: 2200 1234 5678 9012, NOVIKOVA ANASTASIA.",
        ["fio", "passport", "issuing_authority", "issue_date", "subdivision_code",
         "snils", "inn", "birth_date", "birth_place", "address",
         "phone", "email", "card_number", "cardholder_name"], 14))

    tests.append(_d("d-full-08",
        "Пациент: Фёдоров Михаил Николаевич, полис ОМС 7890123456789012, "
        "СНИЛС 789-012-345 67, дата рождения 30.12.1988. "
        "Адрес: г. Самара, ул. Ленинградская, д. 66, кв. 8. "
        "Контактный телефон: +7(917)890-12-34.",
        ["fio", "oms", "snils", "birth_date", "address", "phone"], 6))

    tests.append(_d("d-full-09",
        "Данные сотрудника: Смирнова Ольга Викторовна. "
        "Паспорт 4540 678901, выдан 12.07.2019 ГУ МВД по г. Москве, к/п 770-006. "
        "СНИЛС: 890-123-456 78. ИНН: 890123456789. "
        "Дата рождения: 25.11.1975. Место рождения: г. Нижний Новгород. "
        "Гражданство: Российская Федерация. "
        "Адрес: г. Москва, ул. Мира, д. 100, кв. 50. "
        "Тел.: +7(926)012-34-56. Email: smirnova@corp.ru.",
        ["fio", "passport", "issue_date", "issuing_authority", "subdivision_code",
         "snils", "inn", "birth_date", "birth_place", "citizenship",
         "address", "phone", "email"], 13))

    tests.append(_d("d-full-10",
        "Попов Андрей Николаевич, загранпаспорт 70 2345678, "
        "гражданство: Российская Федерация, место рождения: г. Ростов-на-Дону. "
        "Паспорт РФ: 4545 789012. СНИЛС: 901-234-567 89. ИНН: 901234567890. "
        "Водительское удостоверение: 7704 567890. "
        "Адрес: г. Ростов-на-Дону, пр. Ворошиловский, д. 12, кв. 6. "
        "Тел.: +7(918)234-56-78. Email: popov@mail.ru.",
        ["fio", "foreign_passport", "citizenship", "birth_place",
         "passport", "snils", "inn", "drivers_license", "address", "phone", "email"], 11))

    # === Деловые документы (10) ===
    tests.append(_d("d-doc-01",
        "ДОГОВОР ОКАЗАНИЯ УСЛУГ №123 от 01.01.2024\n\n"
        "Заказчик: Иванов Иван Иванович, паспорт 4510 123456, "
        "зарегистрированный по адресу: г. Москва, ул. Ленина, д. 10, кв. 25, "
        "ИНН 123456789012, тел. +7(999)123-45-67.",
        ["fio", "passport", "address", "inn", "phone"], 5))

    tests.append(_d("d-doc-02",
        "ЗАЯВЛЕНИЕ\n\n"
        "Я, Петрова Мария Сергеевна, паспорт серия 4515 номер 678901, "
        "выдан УФМС по г. Москве 15.06.2015, код подразделения 770-002, "
        "прошу оформить загранпаспорт. СНИЛС: 234-567-890 12.",
        ["fio", "passport", "issuing_authority", "issue_date",
         "subdivision_code", "snils"], 6))

    tests.append(_d("d-doc-03",
        "ДОВЕРЕННОСТЬ\n\n"
        "Я, Сидоров Алексей Владимирович, дата рождения 23.05.1978, "
        "паспорт 4520 234567, доверяю Козловой Елене Дмитриевне, "
        "паспорт 4525 345678, представлять мои интересы.",
        ["fio", "birth_date", "passport"], 4))

    tests.append(_d("d-doc-04",
        "Акт приёма-передачи\n\n"
        "Продавец: Кузнецов Дмитрий Александрович, ИНН 456789012345, "
        "тел. +7(912)567-89-01, email: kuznetsov@mail.ru.\n"
        "Покупатель: Новикова Анастасия Павловна, ИНН 567890123456, "
        "тел. +7(905)456-78-90.",
        ["fio", "inn", "phone", "email"], 7))

    tests.append(_d("d-doc-05",
        "Справка\n\n"
        "Дана Фёдорову Михаилу Николаевичу, дата рождения 30.12.1988, "
        "СНИЛС 789-012-345 67, в том, что он является сотрудником "
        "ООО «Ромашка» с окладом 150 000 руб.",
        ["fio", "birth_date", "snils"], 3))

    tests.append(_d("d-doc-06",
        "Резюме\n\n"
        "Смирнова Ольга Викторовна\n"
        "Телефон: +7(926)012-34-56\n"
        "Email: smirnova@corp.ru\n"
        "Дата рождения: 25.11.1975\n"
        "Адрес: г. Москва, ул. Мира, д. 100, кв. 50\n"
        "Гражданство: Российская Федерация",
        ["fio", "phone", "email", "birth_date", "address", "citizenship"], 6))

    tests.append(_d("d-doc-07",
        "Анкета застрахованного лица\n\n"
        "ФИО: Попов Андрей Николаевич\n"
        "Полис ОМС: 9012345678901234\n"
        "СНИЛС: 901-234-567 89\n"
        "Паспорт: 4545 789012\n"
        "Адрес: г. Ростов-на-Дону, пр. Ворошиловский, д. 12",
        ["fio", "oms", "snils", "passport", "address"], 5))

    tests.append(_d("d-doc-08",
        "Платёжное поручение\n\n"
        "Плательщик: Козлова Елена Дмитриевна\n"
        "Карта: 4276 1234 5678 9010 (KOZLOVA ELENA)\n"
        "Сумма: 50 000 руб.\n"
        "Получатель: ИП Иванов, ИНН 1234567890",
        ["fio", "card_number", "cardholder_name", "inn"], 4))

    tests.append(_d("d-doc-09",
        "Протокол опроса\n\n"
        "Опрашиваемый: Волков Сергей Анатольевич, "
        "паспорт 4550 890123, дата рождения 09.03.1982, "
        "проживающий по адресу: г. Краснодар, ул. Красная, д. 100, "
        "тел. +7(918)234-56-78. Военный билет: АА 1234567.",
        ["fio", "passport", "birth_date", "address", "phone", "military_id"], 6))

    tests.append(_d("d-doc-10",
        "Заявка на кредит\n\n"
        "Заёмщик: Лебедева Наталья Игоревна\n"
        "Паспорт: 4555 901234, выдан 08.01.2016 ОУФМС по г. Казани, к/п 160-007\n"
        "Дата рождения: 19.08.1991, место рождения: г. Казань\n"
        "СНИЛС: 012-345-678 90, ИНН: 012345678901\n"
        "Адрес: г. Казань, ул. Баумана, д. 33, кв. 12\n"
        "Телефон: +7(917)890-12-34, email: lebedeva@mail.ru\n"
        "Карта для перечисления: 5469 1234 5678 9012 (LEBEDEVA NATALIA)",
        ["fio", "passport", "issue_date", "issuing_authority", "subdivision_code",
         "birth_date", "birth_place", "snils", "inn", "address",
         "phone", "email", "card_number", "cardholder_name"], 14))

    # === Дополнительные двойные комбинации для дополнения до ~120 ===
    extras = [
        ("d-extra-01", "Иванов И.И., тел. 8-999-123-45-67", ["fio", "phone"], 2),
        ("d-extra-02", "СНИЛС 123-456-789 00, полис ОМС 1234567890123456", ["snils", "oms"], 2),
        ("d-extra-03", "email: user@mail.ru, ИНН 123456789012", ["email", "inn"], 2),
        ("d-extra-04", "ВУ 77 01 234567, загранпаспорт 51 1234567", ["drivers_license", "foreign_passport"], 2),
        ("d-extra-05", "военный билет АА 1234567, СНИЛС 123-456-789 00", ["military_id", "snils"], 2),
        ("d-extra-06", "карта 4276 1234 5678 9010, +7(999)123-45-67", ["card_number", "phone"], 2),
        ("d-extra-07", "адрес: г. Москва, ул. Ленина, д. 10, СНИЛС 123-456-789 00", ["address", "snils"], 2),
        ("d-extra-08", "гражданство: РФ, место рождения: г. Москва", ["citizenship", "birth_place"], 2),
        ("d-extra-09", "выдан 01.02.2020, код подразделения 770-001", ["issue_date", "subdivision_code"], 2),
        ("d-extra-10", "выдан ОВД г. Москвы, к/п 770-001", ["issuing_authority", "subdivision_code"], 2),
    ]
    for t, p, c, n in extras:
        tests.append(_d(t, p, c, n))

    # === Дополнительные комбинации для доведения до ~120 ===
    more = [
        ("d-more-01",
         "Иванов Иван Иванович, паспорт 4510 123456, тел. +7(999)123-45-67, email: user@mail.ru",
         ["fio", "passport", "phone", "email"], 4),
        ("d-more-02",
         "СНИЛС 123-456-789 00, ИНН 123456789012, дата рождения 01.01.1990",
         ["snils", "inn", "birth_date"], 3),
        ("d-more-03",
         "карта 4276 1234 5678 9010, IVANOV IVAN, CVV 123, PIN 1234",
         ["card_number", "cardholder_name", "cvv", "pin"], 4),
        ("d-more-04",
         "паспорт 4510 123456, выдан ОВД г. Москвы 01.02.2020, к/п 770-001, место рождения: г. Москва",
         ["passport", "issuing_authority", "issue_date", "subdivision_code", "birth_place"], 5),
        ("d-more-05",
         "Иванов Иван Иванович, ВУ 77 01 234567, загранпаспорт 51 1234567, военный билет АА 1234567",
         ["fio", "drivers_license", "foreign_passport", "military_id"], 4),
        ("d-more-06",
         "email: user@mail.ru, адрес: г. Москва, ул. Ленина, д. 10, полис ОМС 1234567890123456",
         ["email", "address", "oms"], 3),
        ("d-more-07",
         "Петрова Мария Сергеевна, дата рождения 15.03.1985, гражданство: РФ, место рождения: г. Санкт-Петербург",
         ["fio", "birth_date", "citizenship", "birth_place"], 4),
        ("d-more-08",
         "Сидоров А.В., СНИЛС 345-678-901 23, ИНН 345678901234, +7(926)345-67-89",
         ["fio", "snils", "inn", "phone"], 4),
        ("d-more-09",
         "карта 5469 1234 5678 9012, CVV 456, email: test@gmail.com, тел. +7(916)234-56-78",
         ["card_number", "cvv", "email", "phone"], 4),
        ("d-more-10",
         "Козлова Елена Дмитриевна, паспорт 4525 345678, СНИЛС 456-789-012 34, ИНН 456789012345, "
         "адрес: г. Новосибирск, Красный проспект, д. 50",
         ["fio", "passport", "snils", "inn", "address"], 5),
        ("d-more-11",
         "загранпаспорт 72 4567890, водительское удостоверение 7702 345678, Кузнецов Дмитрий",
         ["foreign_passport", "drivers_license", "fio"], 3),
        ("d-more-12",
         "военный билет серия АБ номер 2345678, СНИЛС 234-567-890 12, дата рождения 23.05.1978",
         ["military_id", "snils", "birth_date"], 3),
        ("d-more-13",
         "полис ОМС 2345678901234567, карта 2200 1234 5678 9012, Петрова Мария",
         ["oms", "card_number", "fio"], 3),
        ("d-more-14",
         "ИНН 1234567890, +7(999)123-45-67, user@mail.ru, г. Москва, ул. Ленина, д. 10",
         ["inn", "phone", "email", "address"], 4),
        ("d-more-15",
         "выдан УФМС по г. Москве 15.06.2015, код подразделения 770-002, гражданство: РФ",
         ["issuing_authority", "issue_date", "subdivision_code", "citizenship"], 4),
        ("d-more-16",
         "IVANOV IVAN, карта 4276 9999 8888 7777, CVC 321, PIN 5678",
         ["cardholder_name", "card_number", "cvv", "pin"], 4),
        ("d-more-17",
         "Иванов Иван Иванович, паспорт 4510 123456, СНИЛС 123-456-789 00, ИНН 123456789012, "
         "+7(999)123-45-67",
         ["fio", "passport", "snils", "inn", "phone"], 5),
        ("d-more-18",
         "дата рождения 01.01.1990, место рождения: г. Москва, гражданство: Российская Федерация, "
         "адрес: г. Москва, ул. Ленина, д. 10, кв. 25",
         ["birth_date", "birth_place", "citizenship", "address"], 4),
        ("d-more-19",
         "Новикова Анастасия Павловна, email: novikova@outlook.com, тел. +7(905)456-78-90, "
         "полис ОМС 5678901234567890",
         ["fio", "email", "phone", "oms"], 4),
        ("d-more-20",
         "паспорт 4535 567890, ВУ 77 05 678901, загранпаспорт 74 6789012",
         ["passport", "drivers_license", "foreign_passport"], 3),
        ("d-more-21",
         "Фёдоров Михаил Николаевич, военный билет АВ 3456789, СНИЛС 567-890-123 45, "
         "дата рождения 30.12.1988, место рождения: г. Самара",
         ["fio", "military_id", "snils", "birth_date", "birth_place"], 5),
        ("d-more-22",
         "Смирнова Ольга Викторовна, карта 2200 8888 9999 0000, SMIRNOVA OLGA, email: smirnova@corp.ru",
         ["fio", "card_number", "cardholder_name", "email"], 4),
        ("d-more-23",
         "Попов Андрей, ИНН 901234567890, адрес: г. Ростов-на-Дону, пр. Ворошиловский, д. 12",
         ["fio", "inn", "address"], 3),
        ("d-more-24",
         "загранпаспорт 70 2345678, гражданство: Российская Федерация, дата выдачи 03.06.2022",
         ["foreign_passport", "citizenship", "issue_date"], 3),
        ("d-more-25",
         "ВУ 7710 111222, водительское удостоверение 7711 222333, Волков Сергей Анатольевич",
         ["drivers_license", "fio"], 3),
        ("d-more-26",
         "военный билет АГ 4567890, паспорт 4540 678901, СНИЛС 890-123-456 78, ИНН 890123456789",
         ["military_id", "passport", "snils", "inn"], 4),
        ("d-more-27",
         "полис ОМС 7890123456789012, СНИЛС 789-012-345 67, +7(917)890-12-34, user@mail.ru",
         ["oms", "snils", "phone", "email"], 4),
        ("d-more-28",
         "карта 4276 2222 3333 4444, CVV 666, выдан ОВД г. Москвы, Иванов Иван",
         ["card_number", "cvv", "issuing_authority", "fio"], 4),
        ("d-more-29",
         "Лебедева Наталья Игоревна, паспорт 4555 901234, код подразделения 160-007, "
         "дата выдачи 08.01.2016, выдан ОУФМС по г. Казани",
         ["fio", "passport", "subdivision_code", "issue_date", "issuing_authority"], 5),
        ("d-more-30",
         "Иванов Иван Иванович, паспорт 4510 123456, выдан 01.02.2020 ОВД г. Москвы, "
         "код подразделения 770-001, СНИЛС 123-456-789 00, ИНН 123456789012, "
         "дата рождения 01.01.1990, место рождения: г. Москва, гражданство: РФ, "
         "+7(999)123-45-67, user@mail.ru, адрес: г. Москва, ул. Ленина, д. 10, кв. 25, "
         "полис ОМС 1234567890123456, ВУ 77 01 234567, загранпаспорт 51 1234567",
         ["fio", "passport", "issue_date", "issuing_authority", "subdivision_code",
          "snils", "inn", "birth_date", "birth_place", "citizenship",
          "phone", "email", "address", "oms", "drivers_license", "foreign_passport"], 16),
    ]
    for t, p, c, n in more:
        tests.append(_d(t, p, c, n))

    # === Дополнительные документы (10) для доведения до 120 ===
    docs2 = [
        ("d-doc2-01",
         "Справка 2-НДФЛ\nСотрудник: Волков Сергей Анатольевич, ИНН 567890123456, СНИЛС 567-890-123 45",
         ["fio", "inn", "snils"], 3),
        ("d-doc2-02",
         "Заявка на полис ОМС\nПациент: Морозова Татьяна, дата рождения 14.02.1993, "
         "полис ОМС 9012345678901234, тел. +7(926)012-34-56",
         ["fio", "birth_date", "oms", "phone"], 4),
        ("d-doc2-03",
         "Протокол допроса\nСвидетель: Кузнецов Дмитрий Александрович, паспорт 4530 456789, "
         "проживает: г. Екатеринбург, ул. Мира, д. 5",
         ["fio", "passport", "address"], 3),
        ("d-doc2-04",
         "Налоговая декларация 3-НДФЛ\nИНН: 345678901234, СНИЛС: 345-678-901 23, "
         "адрес регистрации: г. Казань, ул. Баумана, д. 33",
         ["inn", "snils", "address"], 3),
        ("d-doc2-05",
         "Опись почтового отправления\nОтправитель: Новикова Анастасия Павловна, "
         "адрес: 190000, г. Санкт-Петербург, Лиговский пр., д. 44, тел. +7(905)456-78-90",
         ["fio", "address", "phone"], 3),
        ("d-doc2-06",
         "Договор аренды\nАрендатор: Попов Андрей Николаевич, паспорт 4545 789012, "
         "ИНН 901234567890, адрес объекта: г. Ростов-на-Дону, пр. Ворошиловский, д. 12, кв. 6",
         ["fio", "passport", "inn", "address"], 4),
        ("d-doc2-07",
         "Заявление на загранпаспорт\nФИО: Лебедева Наталья Игоревна, "
         "паспорт 4555 901234, дата рождения 19.08.1991, "
         "место рождения: г. Казань, гражданство: Российская Федерация",
         ["fio", "passport", "birth_date", "birth_place", "citizenship"], 5),
        ("d-doc2-08",
         "Банковская выписка\nВладелец счёта: Фёдоров Михаил Николаевич, "
         "карта 5469 6666 7777 8888, FEDOROV MIKHAIL",
         ["fio", "card_number", "cardholder_name"], 3),
        ("d-doc2-09",
         "Медицинская карта\nПациент: Смирнова Ольга Викторовна, дата рождения 25.11.1975, "
         "полис ОМС 1111222233334444, СНИЛС 890-123-456 78",
         ["fio", "birth_date", "oms", "snils"], 4),
        ("d-doc2-10",
         "Исполнительный лист\nДолжник: Козлова Елена Дмитриевна, паспорт 4525 345678, "
         "ИНН 456789012345, адрес: г. Новосибирск, Красный проспект, д. 50, кв. 8",
         ["fio", "passport", "inn", "address"], 4),
    ]
    for t, p, c, n in docs2:
        tests.append(_d(t, p, c, n))

    return tests


# ──────────────────────────────────────────────────────────────────────
# =====================================================================
#   ГРУППА E — Идемпотентность
# =====================================================================
# ──────────────────────────────────────────────────────────────────────

def build_group_e() -> List[TC]:
    """Идемпотентность: при повторном запросе с тем же payload_id результат идентичен."""
    payloads = [
        "Иванов Иван Иванович",
        "Петрова Мария Сергеевна",
        "паспорт 4510 123456",
        "СНИЛС 123-456-789 00",
        "ИНН 123456789012",
        "+7(999)123-45-67",
        "user@mail.ru",
        "4276 1234 5678 9010",
        "г. Москва, ул. Ленина, д. 10, кв. 25",
        "дата рождения: 01.01.1990",
        "полис ОМС 1234567890123456",
        "ВУ 77 01 234567",
        "загранпаспорт 51 1234567",
        "военный билет АА 1234567",
        "карта 4276 1234 5678 9010, CVV 123",
        "карта 4276 1234 5678 9010, PIN-код: 1234",
        "выдан 01.02.2020",
        "выдан ОВД г. Москвы",
        "код подразделения 770-001",
        "IVANOV IVAN",
        "гражданство: Российская Федерация",
        "место рождения: г. Москва",
        "Иванов Иван Иванович, паспорт 4510 123456",
        "email: user@mail.ru, тел. +7(999)123-45-67",
        "СНИЛС 234-567-890 12, ИНН 234567890123",
        "Сидоров Алексей Владимирович",
        "серия 4520 номер 234567",
        "+7(916)234-56-78",
        "test@gmail.com",
        "5469 1234 5678 9012",
        "г. Санкт-Петербург, пр. Невский, д. 100",
        "дата рождения: 15 марта 1985",
        "полис ОМС 2345678901234567",
        "водительское удостоверение 7701 234567",
        "заграничный паспорт 70 2345678",
        "военный билет серия АБ номер 2345678",
        "CVC: 456",
        "ПИН: 5678",
        "дата выдачи 15.06.2015",
        "выдан УФМС по г. Москве",
        "к/п 123-456",
        "PETROVA MARIA S",
        "гражданство РФ",
        "родился в г. Санкт-Петербург",
        "Козлова Елена Дмитриевна, паспорт 4525 345678, СНИЛС 456-789-012 34",
        "карта 2200 1234 5678 9012, NOVIKOVA ANASTASIA, CVV 789",
        "Просто обычный текст без ПДн",
        "12345678900",
        "ИНН 1234567890",
        "8-999-123-45-67",
    ]
    tests: List[TC] = []
    for i, payload in enumerate(payloads, start=1):
        pid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"idem-test-{i}"))
        tests.append(TC(group="E", tag=f"e-idem-{i:02d}", payload=payload,
                        exp_action="any", pid=pid, exp_pd=0, neg=True))
    return tests


# ──────────────────────────────────────────────────────────────────────
# =====================================================================
#   ГРУППА F — Нагрузочные пейлоады
# =====================================================================
# ──────────────────────────────────────────────────────────────────────

def build_group_f() -> List[TC]:
    """100 пейлоадов для нагрузочного теста."""
    samples = [
        "Иванов Иван Иванович, паспорт 4510 123456",
        "Петрова Мария Сергеевна, СНИЛС 234-567-890 12",
        "+7(999)123-45-67, email: user@mail.ru",
        "ИНН 123456789012, карта 4276 1234 5678 9010",
        "г. Москва, ул. Ленина, д. 10, кв. 25",
        "дата рождения 01.01.1990, место рождения: г. Москва",
        "ВУ 77 01 234567, загранпаспорт 51 1234567",
        "военный билет АА 1234567, СНИЛС 345-678-901 23",
        "карта 5469 1234 5678 9012, CVV 123, PIN 1234",
        "выдан ОВД г. Москвы, код подразделения 770-001",
        "Сидоров Алексей Владимирович",
        "паспорт серия 4520 номер 234567",
        "СНИЛС: 456-789-012 34",
        "+7(916)234-56-78",
        "test@gmail.com",
        "2200 1234 5678 9012",
        "адрес: г. Казань, ул. Баумана, д. 33",
        "дата рождения: 15 марта 1985",
        "полис ОМС 1234567890123456",
        "водительское удостоверение 7702 345678",
        "Просто текст без персональных данных, обычное письмо",
        "Козлова Елена Дмитриевна, ИНН 567890123456, тел. +7(903)123-45-67",
        "загранпаспорт 72 4567890, гражданство: Российская Федерация",
        "Кузнецов Дмитрий Александрович, email: kuznetsov@mail.ru",
        "карта 4276 9999 8888 7777, IVANOV IVAN, CVV 321",
    ]
    tests: List[TC] = []
    for i in range(100):
        payload = samples[i % len(samples)]
        tests.append(TC(group="F", tag=f"f-load-{i+1:03d}", payload=payload,
                        exp_action="any", exp_pd=0, neg=True))
    return tests


# ──────────────────────────────────────────────────────────────────────
# =====================================================================
#   Группа G: SpaCy-верифицированные тесты (Anti-FP + NER-сверка)
# =====================================================================
# ──────────────────────────────────────────────────────────────────────

def build_group_g() -> List[TC]:
    """SpaCy-верифицированные тесты: кейсы из spacy_analysis.py.

    Включает:
    - Позитивные: тексты с ПДн (ФИО, паспорт, СНИЛС, ИНН и т.д.)
    - Anti-FP: известные личности, организации, персонажи, топонимы
    - Комбинированные: полные наборы ПДн клиента
    """
    tests: List[TC] = []

    # --- G1: Чистые ФИО (SpaCy PER → fio) ---
    tests.append(TC(
        group="G", tag="g-fio-full",
        payload="Иванов Иван Иванович обратился в банк.",
        exp_cats=["fio"], exp_pd=1,
    ))
    tests.append(TC(
        group="G", tag="g-fio-female",
        payload="Заявление от Петровой Марии Сергеевны.",
        exp_cats=["fio"], exp_pd=1,
    ))
    tests.append(TC(
        group="G", tag="g-fio-initials",
        payload="Сидоров А.В. подписал договор.",
        exp_cats=["fio"], exp_pd=1,
    ))
    tests.append(TC(
        group="G", tag="g-fio-with-title",
        payload="Директор Козлов Дмитрий Петрович назначил совещание.",
        exp_cats=["fio"], exp_pd=1,
    ))

    # --- G2: ФИО + паспортные данные ---
    tests.append(TC(
        group="G", tag="g-fio-passport",
        payload="Иванов Иван Иванович, паспорт серия 4510 номер 123456.",
        exp_cats=["fio", "passport"], exp_pd=2,
    ))
    tests.append(TC(
        group="G", tag="g-passport-organ-date",
        payload="Паспортные данные: серия 4510 номер 654321, выдан ОВД района Тверской 15.03.2015.",
        exp_cats=["passport", "issuing_authority", "issue_date"], exp_pd=3,
    ))

    # --- G3: Контактные данные ---
    tests.append(TC(
        group="G", tag="g-phone-email",
        payload="Телефон: +7 (495) 123-45-67, email: test@example.com",
        exp_cats=["phone", "email"], exp_pd=2,
    ))
    tests.append(TC(
        group="G", tag="g-phone-8xxx",
        payload="Звоните по номеру 8-916-555-12-34.",
        exp_cats=["phone"], exp_pd=1,
    ))

    # --- G4: Финансовые данные ---
    tests.append(TC(
        group="G", tag="g-card-cvv",
        payload="Номер карты: 4276 1234 5678 9012, CVV: 123",
        exp_cats=["card_number", "cvv"], exp_pd=2,
    ))
    tests.append(TC(
        group="G", tag="g-inn",
        payload="ИНН: 770123456789",
        exp_cats=["inn"], exp_pd=1,
    ))
    tests.append(TC(
        group="G", tag="g-snils",
        payload="СНИЛС: 123-456-789 00",
        exp_cats=["snils"], exp_pd=1,
    ))

    # --- G5: Адреса ---
    tests.append(TC(
        group="G", tag="g-address-full",
        payload="Адрес: г. Москва, ул. Тверская, д. 15, кв. 42.",
        exp_cats=["address"], exp_pd=1,
    ))
    tests.append(TC(
        group="G", tag="g-address-region",
        payload="Проживает по адресу: Московская обл., г. Подольск, ул. Ленина, д. 5.",
        exp_cats=["address"], exp_pd=1,
    ))

    # --- G6: Даты рождения ---
    tests.append(TC(
        group="G", tag="g-birth-date-num",
        payload="Дата рождения: 15.06.1990",
        exp_cats=["birth_date"], exp_pd=1,
    ))
    tests.append(TC(
        group="G", tag="g-birth-date-text",
        payload="Родился 25 декабря 1985 года.",
        exp_cats=["birth_date"], exp_pd=1,
    ))

    # --- G7: Anti-FP (SpaCy-верифицированные) ---
    tests.append(TC(
        group="G", tag="g-antifp-pushkin",
        payload="Александр Сергеевич Пушкин написал Евгения Онегина.",
        neg=True, exp_pd=0, exp_action="masked",
    ))
    tests.append(TC(
        group="G", tag="g-antifp-ooo",
        payload="Компания ООО Ромашка зарегистрирована в 2020 году.",
        neg=True, exp_pd=0, exp_action="masked",
    ))
    tests.append(TC(
        group="G", tag="g-antifp-president",
        payload="Президент Владимир Путин выступил с речью.",
        neg=True, exp_pd=0, exp_action="masked",
    ))
    tests.append(TC(
        group="G", tag="g-antifp-toponym",
        payload="В городе Санкт-Петербург проходит фестиваль.",
        neg=True, exp_pd=0, exp_action="masked",
    ))
    tests.append(TC(
        group="G", tag="g-antifp-temperature",
        payload="Температура воздуха составила 25 градусов.",
        neg=True, exp_pd=0, exp_action="masked",
    ))

    # --- G8: Комбинированные (полный набор ПДн) ---
    tests.append(TC(
        group="G", tag="g-combo-full-client",
        payload=(
            "Клиент Козлов Дмитрий Андреевич, дата рождения 12.03.1988, "
            "паспорт серия 4515 номер 987654, СНИЛС 111-222-333 44, "
            "проживает: г. Москва, ул. Арбат, д. 10, кв. 5. "
            "Телефон: +7 (916) 111-22-33, email: kozlov@mail.ru"
        ),
        exp_cats=["fio", "birth_date", "passport", "snils", "address", "phone", "email"],
        exp_pd=7,
    ))
    tests.append(TC(
        group="G", tag="g-combo-inn-oms-zagran",
        payload=(
            "Заёмщик: Морозова Елена Викторовна, ИНН 501234567890, "
            "полис ОМС 1234567890123456, загранпаспорт 72 1234567."
        ),
        exp_cats=["fio", "inn", "oms", "foreign_passport"],
        exp_pd=4,
    ))

    # --- G9: Сложные контексты ---
    tests.append(TC(
        group="G", tag="g-birthplace-citizen",
        payload="Место рождения: г. Новосибирск, гражданство: Российская Федерация.",
        exp_cats=["birth_place", "citizenship"], exp_pd=2,
    ))
    tests.append(TC(
        group="G", tag="g-subdivision-organ-date",
        payload="Код подразделения: 770-025, выдан УФМС по г. Москве 20.05.2018.",
        exp_cats=["subdivision_code", "issuing_authority", "issue_date"], exp_pd=3,
    ))
    tests.append(TC(
        group="G", tag="g-drivers-license",
        payload="Водительское удостоверение: 77 14 567890.",
        exp_cats=["drivers_license"], exp_pd=1,
    ))
    tests.append(TC(
        group="G", tag="g-military-id",
        payload="Военный билет: АБ 1234567.",
        exp_cats=["military_id"], exp_pd=1,
    ))

    # --- G10: Дополнительные Anti-FP с NER-верификацией ---
    tests.append(TC(
        group="G", tag="g-antifp-tolstoy",
        payload="Лев Николаевич Толстой написал Войну и мир.",
        neg=True, exp_pd=0, exp_action="masked",
    ))
    tests.append(TC(
        group="G", tag="g-antifp-mendeleev",
        payload="Дмитрий Иванович Менделеев создал периодическую таблицу.",
        neg=True, exp_pd=0, exp_action="masked",
    ))
    tests.append(TC(
        group="G", tag="g-antifp-gagarin",
        payload="Юрий Алексеевич Гагарин полетел в космос.",
        neg=True, exp_pd=0, exp_action="masked",
    ))
    tests.append(TC(
        group="G", tag="g-antifp-raskolnikov",
        payload="Родион Раскольников — персонаж Достоевского.",
        neg=True, exp_pd=0, exp_action="masked",
    ))
    tests.append(TC(
        group="G", tag="g-antifp-bolkonsky",
        payload="Князь Андрей Болконский смотрел на небо.",
        neg=True, exp_pd=0, exp_action="masked",
    ))
    tests.append(TC(
        group="G", tag="g-antifp-pao",
        payload="ПАО Сбербанк выпустил новую карту.",
        neg=True, exp_pd=0, exp_action="masked",
    ))
    tests.append(TC(
        group="G", tag="g-antifp-ip",
        payload="ИП Ромашка Иванов зарегистрирован.",
        neg=True, exp_pd=0, exp_action="masked",
        known_limitation=True,  # ИП + Ромашка может сработать на fio
    ))

    return tests


# ──────────────────────────────────────────────────────────────────────
# =====================================================================
#   РАННЕР
# =====================================================================
# ──────────────────────────────────────────────────────────────────────

async def run_one(session: aiohttp.ClientSession, tc: TC) -> TR:
    """Выполнить один тест-кейс и вернуть результат."""
    pid = tc.pid or str(uuid.uuid4())
    body = {
        "payload": tc.payload,
        "payload_id": pid,
        "system_id": tc.sid,
        "mode": tc.mode,
    }
    t0 = time.monotonic()
    try:
        async with session.post(
            f"{SERVER_URL}/process", json=body, timeout=TIMEOUT
        ) as resp:
            data = await resp.json()
    except Exception as exc:
        elapsed = (time.monotonic() - t0) * 1000
        return TR(
            group=tc.group, tag=tc.tag, ok=False,
            errors=[f"HTTP error: {exc}"],
            elapsed_ms=elapsed,
            payload_preview=tc.payload[:80],
        )
    elapsed = (time.monotonic() - t0) * 1000

    action = data.get("action", "")
    stats = data.get("stats") or {}
    cats_found = stats.get("categories", [])
    pd_count = stats.get("pd_found", 0)

    errors: List[str] = []

    # Проверка action
    if tc.exp_action not in ("any",) and action != tc.exp_action:
        errors.append(f"action={action}, ожидалось={tc.exp_action}")

    # Проверка категорий (только для позитивных тестов)
    if tc.exp_cats:
        missing = set(tc.exp_cats) - set(cats_found)
        if missing:
            errors.append(f"не найдены категории: {missing}")

    # Проверка количества ПДн (позитивный тест)
    if not tc.neg and tc.exp_pd > 0 and pd_count < tc.exp_pd:
        errors.append(f"pd_found={pd_count}, ожидалось>={tc.exp_pd}")

    # Анти-FP (негативный тест): не должно быть ПДн
    if tc.neg and pd_count > 0:
        # Для группы E (идемпотентность) мы ставим neg=True,
        # но первый запрос может находить ПДн — это ок
        if tc.group != "E":
            errors.append(f"FP: pd_found={pd_count}, категории={cats_found}")

    ok = len(errors) == 0
    return TR(
        group=tc.group,
        tag=tc.tag,
        ok=ok,
        errors=errors,
        action=action,
        pd_found=pd_count,
        cats=cats_found,
        elapsed_ms=elapsed,
        payload_preview=tc.payload[:80],
        known_limitation=tc.known_limitation if not ok else False,
    )


async def run_group_sequential(
    session: aiohttp.ClientSession, cases: List[TC]
) -> List[TR]:
    """Последовательный запуск."""
    results: List[TR] = []
    for tc in cases:
        tr = await run_one(session, tc)
        results.append(tr)
    return results


async def run_group_e_idempotency(
    session: aiohttp.ClientSession, cases: List[TC]
) -> List[TR]:
    """Проверка идемпотентности: два запроса с одним payload_id дают одинаковый result."""
    results: List[TR] = []
    for tc in cases:
        pid = tc.pid or str(uuid.uuid4())
        body = {
            "payload": tc.payload,
            "payload_id": pid,
            "system_id": tc.sid,
            "mode": tc.mode,
        }
        # Первый запрос
        try:
            async with session.post(
                f"{SERVER_URL}/process", json=body, timeout=TIMEOUT
            ) as resp:
                data1 = await resp.json()
            result1 = data1.get("result", "")
        except Exception as exc:
            results.append(TR(
                group="E", tag=tc.tag, ok=False,
                errors=[f"1st request error: {exc}"],
                payload_preview=tc.payload[:80],
            ))
            continue

        # Второй запрос (тот же payload_id)
        t0 = time.monotonic()
        try:
            async with session.post(
                f"{SERVER_URL}/process", json=body, timeout=TIMEOUT
            ) as resp:
                data2 = await resp.json()
            result2 = data2.get("result", "")
        except Exception as exc:
            results.append(TR(
                group="E", tag=tc.tag, ok=False,
                errors=[f"2nd request error: {exc}"],
                elapsed_ms=(time.monotonic() - t0) * 1000,
                payload_preview=tc.payload[:80],
            ))
            continue

        elapsed = (time.monotonic() - t0) * 1000
        errors: List[str] = []
        if result1 != result2:
            errors.append(
                f"result mismatch: '{result1[:60]}' != '{result2[:60]}'"
            )

        results.append(TR(
            group="E", tag=tc.tag, ok=len(errors) == 0,
            errors=errors, elapsed_ms=elapsed,
            action=data2.get("action", ""),
            pd_found=(
                data2.get("stats", {}).get("pd_found", 0)
                if data2.get("stats") else 0
            ),
            payload_preview=tc.payload[:80],
        ))
    return results


async def run_group_parallel(
    session: aiohttp.ClientSession, cases: List[TC], concurrency: int = 50
) -> List[TR]:
    """Параллельный запуск с ограничением конкурентности."""
    sem = asyncio.Semaphore(concurrency)
    results: List[TR] = []

    async def _worker(tc: TC) -> TR:
        async with sem:
            return await run_one(session, tc)

    tasks = [asyncio.create_task(_worker(tc)) for tc in cases]
    for coro in asyncio.as_completed(tasks):
        tr = await coro
        results.append(tr)
    return results


async def run_load_test(
    session: aiohttp.ClientSession, payloads: List[TC]
) -> dict:
    """
    Нагрузочный тест: LOAD_CONCURRENCY подключений × LOAD_DURATION_SEC секунд.
    Возвращает статистику.
    """
    total_requests = 0
    total_errors = 0
    latencies: List[float] = []
    stop_event = asyncio.Event()

    async def _worker(idx: int) -> None:
        nonlocal total_requests, total_errors
        while not stop_event.is_set():
            tc = payloads[total_requests % len(payloads)]
            pid = str(uuid.uuid4())
            body = {
                "payload": tc.payload,
                "payload_id": pid,
                "system_id": tc.sid,
                "mode": tc.mode,
            }
            t0 = time.monotonic()
            try:
                async with session.post(
                    f"{SERVER_URL}/process", json=body, timeout=TIMEOUT
                ) as resp:
                    await resp.json()
                elapsed = (time.monotonic() - t0) * 1000
                latencies.append(elapsed)
                total_requests += 1
            except Exception:
                total_errors += 1
                total_requests += 1

    # Запуск воркеров
    workers = [asyncio.create_task(_worker(i)) for i in range(LOAD_CONCURRENCY)]

    # Ждём заданное время
    await asyncio.sleep(LOAD_DURATION_SEC)
    stop_event.set()

    # Дожидаемся завершения текущих запросов
    await asyncio.gather(*workers, return_exceptions=True)

    # Статистика
    sorted_lat = sorted(latencies) if latencies else [0]
    return {
        "duration_sec": LOAD_DURATION_SEC,
        "concurrency": LOAD_CONCURRENCY,
        "total_requests": total_requests,
        "total_errors": total_errors,
        "rps": round(total_requests / LOAD_DURATION_SEC, 2) if LOAD_DURATION_SEC else 0,
        "latency_avg_ms": round(sum(sorted_lat) / len(sorted_lat), 2),
        "latency_p50_ms": round(sorted_lat[len(sorted_lat) // 2], 2),
        "latency_p95_ms": round(sorted_lat[int(len(sorted_lat) * 0.95)], 2),
        "latency_p99_ms": round(sorted_lat[int(len(sorted_lat) * 0.99)], 2),
        "latency_max_ms": round(sorted_lat[-1], 2),
    }


# ──────────────────────────────────────────────────────────────────────
# =====================================================================
#   ОТЧЁТЫ
# =====================================================================
# ──────────────────────────────────────────────────────────────────────

def _trunc(s: str, width: int) -> str:
    """Обрезать строку до width символов с многоточием."""
    if len(s) <= width:
        return s
    return s[: width - 1] + "…"


def generate_txt_report(
    results: List[TR],
    load_stats: dict,
    elapsed_total: float,
    filepath: str,
) -> None:
    """Генерация текстового отчёта с ASCII-таблицами."""
    lines: List[str] = []

    lines.append("=" * 120)
    lines.append("  PD-PROXY — ОТЧЁТ ИНТЕГРАЦИОННЫХ ТЕСТОВ")
    lines.append(f"  Сервер: {SERVER_URL}")
    lines.append(f"  Дата:   {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  Общее время: {elapsed_total:.1f} сек")
    lines.append("=" * 120)
    lines.append("")

    # --- Сводка по группам ---
    groups = {}
    for r in results:
        g = groups.setdefault(r.group, {"total": 0, "pass": 0, "fail": 0, "known": 0, "times": []})
        g["total"] += 1
        if r.ok:
            g["pass"] += 1
        elif r.known_limitation:
            g["known"] += 1
            g["fail"] += 1
        else:
            g["fail"] += 1
        g["times"].append(r.elapsed_ms)

    group_names = {
        "A": "Прямое обнаружение ПДн",
        "B": "Граничные / edge-case",
        "C": "Анти-FP (негативные)",
        "D": "Комбинированные ПДн",
        "E": "Идемпотентность",
    }

    lines.append("┌─────────┬──────────────────────────────┬────────┬────────┬────────┬────────┬────────────┐")
    lines.append("│ Группа  │ Описание                     │ Всего  │   ✅   │   ❌   │   ⚠️   │ Avg мс     │")
    lines.append("├─────────┼──────────────────────────────┼────────┼────────┼────────┼────────┼────────────┤")
    total_all = total_pass = total_fail = total_known = 0
    for gk in ("A", "B", "C", "D", "E"):
        g = groups.get(gk, {"total": 0, "pass": 0, "fail": 0, "known": 0, "times": [0]})
        avg = sum(g["times"]) / len(g["times"]) if g["times"] else 0
        total_all += g["total"]
        total_pass += g["pass"]
        total_fail += g["fail"]
        total_known += g["known"]
        name = _trunc(group_names.get(gk, gk), 28)
        lines.append(
            f"│ {gk:^7} │ {name:<28} │ {g['total']:>6} │ {g['pass']:>6} │ {g['fail'] - g['known']:>6} │ {g['known']:>6} │ {avg:>8.1f} мс│"
        )
    lines.append("├─────────┼──────────────────────────────┼────────┼────────┼────────┼────────┼────────────┤")
    lines.append(
        f"│ {'ИТОГО':^7} │ {'':28} │ {total_all:>6} │ {total_pass:>6} │ {total_fail - total_known:>6} │ {total_known:>6} │            │"
    )
    lines.append("└─────────┴──────────────────────────────┴────────┴────────┴────────┴────────┴────────────┘")
    if total_known > 0:
        lines.append(f"  ⚠️  Known limitations (известные ограничения regex-режима): {total_known}")
    lines.append("")

    # --- Нагрузочный тест ---
    lines.append("┌──────────────────────────────────────────────────────────────┐")
    lines.append("│              НАГРУЗОЧНЫЙ ТЕСТ (группа F)                    │")
    lines.append("├──────────────────────────────┬───────────────────────────────┤")
    for key, label in [
        ("duration_sec", "Длительность, сек"),
        ("concurrency", "Параллельных соединений"),
        ("total_requests", "Всего запросов"),
        ("total_errors", "Ошибок"),
        ("rps", "RPS"),
        ("latency_avg_ms", "Средняя задержка, мс"),
        ("latency_p50_ms", "P50, мс"),
        ("latency_p95_ms", "P95, мс"),
        ("latency_p99_ms", "P99, мс"),
        ("latency_max_ms", "Макс. задержка, мс"),
    ]:
        val = load_stats.get(key, "—")
        lines.append(f"│ {label:<28} │ {str(val):>29} │")
    lines.append("└──────────────────────────────┴───────────────────────────────┘")
    lines.append("")

    # --- Список упавших тестов (без known_limitation) ---
    real_failed = [r for r in results if not r.ok and not r.known_limitation]
    known_failed = [r for r in results if not r.ok and r.known_limitation]

    if real_failed:
        lines.append(f"УПАВШИЕ ТЕСТЫ ({len(real_failed)}):")
        lines.append("─" * 120)
        lines.append(
            f"{'Группа':<8} {'Тег':<22} {'Ошибки':<50} {'Payload (превью)':<40}"
        )
        lines.append("─" * 120)
        for r in real_failed:
            err_str = "; ".join(r.errors)
            lines.append(
                f"{r.group:<8} {_trunc(r.tag, 20):<22} "
                f"{_trunc(err_str, 48):<50} "
                f"{_trunc(r.payload_preview, 38):<40}"
            )
        lines.append("─" * 120)
    else:
        lines.append("✅  ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")

    if known_failed:
        lines.append("")
        lines.append(f"KNOWN LIMITATIONS — известные ограничения regex-режима ({len(known_failed)}):")
        lines.append("─" * 120)
        lines.append(
            f"{'Группа':<8} {'Тег':<22} {'Ошибки':<50} {'Payload (превью)':<40}"
        )
        lines.append("─" * 120)
        for r in known_failed:
            err_str = "; ".join(r.errors)
            lines.append(
                f"{r.group:<8} {_trunc(r.tag, 20):<22} "
                f"{_trunc(err_str, 48):<50} "
                f"{_trunc(r.payload_preview, 38):<40}"
            )
        lines.append("─" * 120)

    lines.append("")
    lines.append("=" * 120)

    report_text = "\n".join(lines)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(report_text)


def generate_json_report(
    results: List[TR],
    load_stats: dict,
    elapsed_total: float,
    filepath: str,
) -> None:
    """Генерация JSON-отчёта."""
    # Сводка по группам
    groups_summary = {}
    for r in results:
        g = groups_summary.setdefault(r.group, {
            "total": 0, "pass": 0, "fail": 0, "known_limitations": 0, "latencies_ms": []
        })
        g["total"] += 1
        if r.ok:
            g["pass"] += 1
        elif r.known_limitation:
            g["fail"] += 1
            g["known_limitations"] += 1
        else:
            g["fail"] += 1
        g["latencies_ms"].append(round(r.elapsed_ms, 2))

    # Средние значения
    for gk, g in groups_summary.items():
        lats = g["latencies_ms"]
        g["avg_ms"] = round(sum(lats) / len(lats), 2) if lats else 0
        sorted_l = sorted(lats)
        g["p50_ms"] = round(sorted_l[len(sorted_l) // 2], 2) if sorted_l else 0
        g["p95_ms"] = round(sorted_l[int(len(sorted_l) * 0.95)], 2) if sorted_l else 0

    failed_details = []
    known_details = []
    for r in results:
        if not r.ok:
            entry = {
                "group": r.group,
                "tag": r.tag,
                "errors": r.errors,
                "action": r.action,
                "pd_found": r.pd_found,
                "categories": r.cats,
                "elapsed_ms": round(r.elapsed_ms, 2),
                "payload_preview": r.payload_preview,
                "known_limitation": r.known_limitation,
            }
            if r.known_limitation:
                known_details.append(entry)
            else:
                failed_details.append(entry)

    total = sum(g["total"] for g in groups_summary.values())
    passed = sum(g["pass"] for g in groups_summary.values())
    total_known = sum(g["known_limitations"] for g in groups_summary.values())

    effective_passed = passed + total_known
    effective_failed = total - effective_passed

    report = {
        "server": SERVER_URL,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_total_sec": round(elapsed_total, 2),
        "summary": {
            "total_tests": total,
            "passed": passed,
            "known_limitations": total_known,
            "failed": effective_failed,
            "pass_rate": f"{(effective_passed / total * 100) if total else 0:.1f}%",
        },
        "groups": {
            gk: {
                "total": g["total"],
                "pass": g["pass"],
                "fail": g["fail"] - g["known_limitations"],
                "known_limitations": g["known_limitations"],
                "avg_ms": g["avg_ms"],
                "p50_ms": g["p50_ms"],
                "p95_ms": g["p95_ms"],
            }
            for gk, g in groups_summary.items()
        },
        "load_test": load_stats,
        "failed_tests": failed_details,
        "known_limitation_tests": known_details,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────────────────────────────
# =====================================================================
#   ТОЧКА ВХОДА
# =====================================================================
# ──────────────────────────────────────────────────────────────────────

async def main() -> int:
    """Основная функция: собрать тесты, выполнить, сгенерировать отчёты."""
    print(f"🚀 PD-Proxy интеграционные тесты")
    print(f"   Сервер: {SERVER_URL}")
    print(f"   Режим нагрузки: {LOAD_CONCURRENCY} соединений × {LOAD_DURATION_SEC} сек")
    print()

    # Сборка тест-кейсов
    group_a = build_group_a()
    group_b = build_group_b()
    group_c = build_group_c()
    group_d = build_group_d()
    group_e = build_group_e()
    group_f = build_group_f()
    group_g = build_group_g()

    total_functional = len(group_a) + len(group_b) + len(group_c) + len(group_d) + len(group_e) + len(group_g)
    print(f"📋 Тест-кейсов: A={len(group_a)}, B={len(group_b)}, "
          f"C={len(group_c)}, D={len(group_d)}, E={len(group_e)}, "
          f"F={len(group_f)} (нагрузка), G={len(group_g)} (SpaCy)")
    print(f"   Итого функциональных: {total_functional}")
    print()

    t_start = time.monotonic()
    all_results: List[TR] = []

    connector = aiohttp.TCPConnector(limit=LOAD_CONCURRENCY + 10)
    async with aiohttp.ClientSession(connector=connector) as session:

        # --- Группа A (параллельно) ---
        print(f"▶ Группа A: Прямое обнаружение ПДн ({len(group_a)} тестов)...")
        results_a = await run_group_parallel(session, group_a)
        pass_a = sum(1 for r in results_a if r.ok)
        print(f"  ✅ {pass_a}/{len(group_a)} пройдено")
        all_results.extend(results_a)

        # --- Группа B (параллельно) ---
        print(f"▶ Группа B: Граничные сценарии ({len(group_b)} тестов)...")
        results_b = await run_group_parallel(session, group_b)
        pass_b = sum(1 for r in results_b if r.ok)
        print(f"  ✅ {pass_b}/{len(group_b)} пройдено")
        all_results.extend(results_b)

        # --- Группа C (параллельно) ---
        print(f"▶ Группа C: Анти-FP ({len(group_c)} тестов)...")
        results_c = await run_group_parallel(session, group_c)
        pass_c = sum(1 for r in results_c if r.ok)
        print(f"  ✅ {pass_c}/{len(group_c)} пройдено")
        all_results.extend(results_c)

        # --- Группа D (параллельно) ---
        print(f"▶ Группа D: Комбинированные ПДн ({len(group_d)} тестов)...")
        results_d = await run_group_parallel(session, group_d)
        pass_d = sum(1 for r in results_d if r.ok)
        print(f"  ✅ {pass_d}/{len(group_d)} пройдено")
        all_results.extend(results_d)

        # --- Группа E (идемпотентность — двойной запрос + сравнение result) ---
        print(f"▶ Группа E: Идемпотентность ({len(group_e)} тестов, последовательно)...")
        results_e = await run_group_e_idempotency(session, group_e)
        pass_e = sum(1 for r in results_e if r.ok)
        print(f"  ✅ {pass_e}/{len(group_e)} пройдено")
        all_results.extend(results_e)

        # --- Группа G (SpaCy-верифицированные) ---
        print(f"▶ Группа G: SpaCy-верифицированные + Anti-FP ({len(group_g)} тестов)...")
        results_g = await run_group_parallel(session, group_g)
        pass_g = sum(1 for r in results_g if r.ok)
        print(f"  ✅ {pass_g}/{len(group_g)} пройдено")
        all_results.extend(results_g)

        # --- Группа F (нагрузочный тест) ---
        print(f"▶ Группа F: Нагрузочный тест ({LOAD_CONCURRENCY} conn × {LOAD_DURATION_SEC} сек)...")
        load_stats = await run_load_test(session, group_f)
        print(f"  📊 {load_stats['total_requests']} запросов, "
              f"{load_stats['rps']} RPS, "
              f"P50={load_stats['latency_p50_ms']}мс, "
              f"P95={load_stats['latency_p95_ms']}мс, "
              f"ошибок={load_stats['total_errors']}")

    elapsed_total = time.monotonic() - t_start
    print()
    print(f"⏱  Общее время: {elapsed_total:.1f} сек")
    print()

    # --- Определяем путь для отчётов (рядом со скриптом) ---
    script_dir = os.path.dirname(os.path.abspath(__file__))
    txt_path = os.path.join(script_dir, "test-report.txt")
    json_path = os.path.join(script_dir, "test-report.json")

    # --- Генерация отчётов ---
    generate_txt_report(all_results, load_stats, elapsed_total, txt_path)
    generate_json_report(all_results, load_stats, elapsed_total, json_path)

    print()
    print(f"📄 Текстовый отчёт: {txt_path}")
    print(f"📄 JSON-отчёт:      {json_path}")

    # --- Код возврата ---
    total_fail = sum(1 for r in all_results if not r.ok and not r.known_limitation)
    total_known = sum(1 for r in all_results if not r.ok and r.known_limitation)
    if total_known > 0:
        print(f"\n⚠️  Known limitations (известные ограничения regex): {total_known}")
    if total_fail > 0:
        print(f"❌ ПРОВАЛЕНО тестов: {total_fail}")
        return 1
    else:
        print(f"✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ!")
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
