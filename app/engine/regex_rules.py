"""Regex-правила детекции ПДн (Эшелон 1).

Каждое правило — экземпляр PDRule с категорией, скомпилированным regex,
описанием, приоритетом и флагом необходимости контекста.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Модель правила
# ---------------------------------------------------------------------------

@dataclass
class PDRule:
    """Правило детекции ПДн."""

    category: str
    pattern: re.Pattern[str]
    description: str
    priority: int = 50
    context_required: bool = False


# ---------------------------------------------------------------------------
# Вспомогательные константы
# ---------------------------------------------------------------------------

# Русские месяцы для дат текстом
_MONTHS_RU = (
    r"(?:январ[яь]|феврал[яь]|марта?|апрел[яь]|ма[яй]|июн[яь]"
    r"|июл[яь]|августа?|сентябр[яь]|октябр[яь]|ноябр[яь]|декабр[яь])"
)

# Кириллическая заглавная буква
_CYR_UP = r"[А-ЯЁ]"
# Слово с заглавной кириллической (2+ букв, включая полностью заглавные: ИВАНОВ)
_CYR_WORD_CAP = r"[А-ЯЁ][А-ЯЁа-яё]+"

# Улицы / проспекты / переулки и т.д. — префиксы адреса
_STREET_PREFIXES = (
    r"(?:ул\.|улица|пр\.|пр-т|проспект|пер\.|переулок"
    r"|бульвар|б-р|ш\.|шоссе|наб\.|набережная|пл\.|площадь)"
)

# ---------------------------------------------------------------------------
# Все правила
# ---------------------------------------------------------------------------

ALL_RULES: list[PDRule] = []

# ===== 1. ФИО (fio) ========================================================

# Полное ФИО: Иванов Иван Иванович / ИВАНОВ ИВАН ИВАНОВИЧ
_FIO_FULL = re.compile(
    rf"(?<![А-ЯЁа-яё])"
    rf"(?:{_CYR_WORD_CAP}(?:-{_CYR_WORD_CAP})?)"
    rf"\s+"
    rf"{_CYR_WORD_CAP}"
    rf"\s+"
    rf"{_CYR_WORD_CAP}"
    rf"(?![А-ЯЁа-яё])",
    re.UNICODE,
)
ALL_RULES.append(PDRule(
    category="fio",
    pattern=_FIO_FULL,
    description="ФИО полное (Фамилия Имя Отчество)",
    priority=70,
))

# Сокращённое: Иванов И.И. / Иванов И. И.
_FIO_SHORT = re.compile(
    rf"(?<![А-ЯЁа-яё])"
    rf"(?:{_CYR_WORD_CAP}(?:-{_CYR_WORD_CAP})?)"
    rf"\s+"
    rf"{_CYR_UP}\.\s?{_CYR_UP}\."
    rf"(?![А-ЯЁа-яё])",
    re.UNICODE,
)
ALL_RULES.append(PDRule(
    category="fio",
    pattern=_FIO_SHORT,
    description="ФИО сокращённое (Фамилия И.О.)",
    priority=65,
))

# Инициалы перед фамилией: И.И. Иванов
_FIO_INITIALS_FIRST = re.compile(
    rf"(?<![А-ЯЁа-яё])"
    rf"{_CYR_UP}\.\s?{_CYR_UP}\.\s+"
    rf"(?:{_CYR_WORD_CAP}(?:-{_CYR_WORD_CAP})?)"
    rf"(?![А-ЯЁа-яё])",
    re.UNICODE,
)
ALL_RULES.append(PDRule(
    category="fio",
    pattern=_FIO_INITIALS_FIRST,
    description="ФИО с инициалами впереди (И.О. Фамилия)",
    priority=65,
))

# Фамилия Имя (два слова): Иванов Иван (заглавная + строчные, мин 3 буквы)
_FIO_TWO = re.compile(
    rf"(?<![А-ЯЁа-яё])"
    rf"(?:[А-ЯЁ][а-яё]{{2,}}(?:-[А-ЯЁ][а-яё]{{2,}})?)"
    rf"\s+"
    rf"[А-ЯЁ][а-яё]{{2,}}"
    rf"(?!\s+[А-ЯЁ][а-яё])"
    rf"(?![А-ЯЁа-яё])",
    re.UNICODE,
)
ALL_RULES.append(PDRule(
    category="fio",
    pattern=_FIO_TWO,
    description="Фамилия Имя (2 слова)",
    priority=40,
))

# ===== 2. Дата рождения (birth_date) =======================================

# С контекстом
_BIRTH_DATE_CTX = re.compile(
    r"(?:дата\s+рождения|д\.?\s?р\.?|родил(?:ся|ась)|born|ДР)"
    r"[\s:]*"
    r"(\d{1,2}[./-]\d{1,2}[./-]\d{4})",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="birth_date",
    pattern=_BIRTH_DATE_CTX,
    description="Дата рождения (цифрами с контекстом)",
    priority=80,
    context_required=True,
))

# Текстовая дата с контекстом: «родился 1 января 1990»
_BIRTH_DATE_TEXT = re.compile(
    r"(?:дата\s+рождения|д\.?\s?р\.?|родил(?:ся|ась)|born|ДР)"
    r"[\s:]*"
    rf"(\d{{1,2}}\s+{_MONTHS_RU}\s+\d{{4}}(?:\s*(?:г\.?|года?))?)",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="birth_date",
    pattern=_BIRTH_DATE_TEXT,
    description="Дата рождения (текстом с контекстом)",
    priority=80,
    context_required=True,
))

# ===== 3. Место рождения (birth_place) =====================================

_BIRTH_PLACE = re.compile(
    r"(?:место\s+рождения|родил(?:ся|ась)\s+в|уроженец|уроженка)"
    r"[\s:]*"
    r"(.{5,80}?)(?:[,;.](?:\s|$)|\s*$)",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="birth_place",
    pattern=_BIRTH_PLACE,
    description="Место рождения",
    priority=70,
    context_required=True,
))

# ===== 4. Паспорт (passport) ===============================================

# С контекстом: «паспорт 4509 123456»
_PASSPORT_CTX = re.compile(
    r"(?:паспорт|серия(?:\s+и\s+номер)?|passport)"
    r"[\s:]*"
    r"(\d{2}\s?\d{2}\s?\d{6})",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="passport",
    pattern=_PASSPORT_CTX,
    description="Паспорт с контекстным словом",
    priority=90,
    context_required=True,
))

# Без контекста: формат «4509 123456» (4 + пробел + 6)
_PASSPORT_NO_CTX = re.compile(
    r"\b(\d{4})\s(\d{6})\b",
)
ALL_RULES.append(PDRule(
    category="passport",
    pattern=_PASSPORT_NO_CTX,
    description="Паспорт без контекста (NNNN NNNNNN)",
    priority=30,
))

# ===== 5. Гражданство (citizenship) ========================================

_CITIZENSHIP = re.compile(
    r"(?:гражданство|гражданин|гражданка)"
    r"[\s:]*"
    r"(.{2,50}?)(?:[,;.](?:\s|$)|\s*$)",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="citizenship",
    pattern=_CITIZENSHIP,
    description="Гражданство",
    priority=60,
    context_required=True,
))

# ===== 6. Орган выдачи (issuing_authority) ==================================

_ISSUING_AUTHORITY = re.compile(
    r"(?:выдан)\s+"
    r"((?:ОВД|УФМС|ОУФМС|МВД|ГУ МВД|отделом|отделением|УМВД|ТП).{5,120}?)"
    r"(?:\d{2}\.\d{2}\.\d{4}|код\s+подразделения|$)",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="issuing_authority",
    pattern=_ISSUING_AUTHORITY,
    description="Орган выдачи документа",
    priority=60,
    context_required=True,
))

# ===== 7. Код подразделения (subdivision_code) ==============================

_SUBDIVISION_CODE_CTX = re.compile(
    r"(?:код\s+подразделения|к/?п)"
    r"[\s:]*"
    r"(\d{3}-\d{3})",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="subdivision_code",
    pattern=_SUBDIVISION_CODE_CTX,
    description="Код подразделения с контекстом",
    priority=70,
    context_required=True,
))

_SUBDIVISION_CODE_BARE = re.compile(
    r"\b(\d{3}-\d{3})\b",
)
ALL_RULES.append(PDRule(
    category="subdivision_code",
    pattern=_SUBDIVISION_CODE_BARE,
    description="Код подразделения без контекста (NNN-NNN)",
    priority=20,
))

# ===== 8. Дата выдачи (issue_date) =========================================

_ISSUE_DATE = re.compile(
    r"(?:дата\s+выдачи|выдан)"
    r"[\s:]*"
    r"(\d{1,2}[./-]\d{1,2}[./-]\d{4})",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="issue_date",
    pattern=_ISSUE_DATE,
    description="Дата выдачи документа",
    priority=70,
    context_required=True,
))

# ===== 9. Водительское удостоверение (drivers_license) ======================

_DRIVERS_LICENSE = re.compile(
    r"(?:водительское\s+удостоверение|в/?у\b|ВУ\b)"
    r"[\s:]*"
    r"(\d{2}\s?[А-ЯA-Z]{2}\s?\d{6}|\d{4}\s?\d{6})",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="drivers_license",
    pattern=_DRIVERS_LICENSE,
    description="Водительское удостоверение",
    priority=80,
    context_required=True,
))

# ===== 10. Адрес (address) =================================================

# Структурированный адрес с ключевыми словами улицы
_ADDRESS_STREET = re.compile(
    rf"(?:(?:г\.|город)\s+[А-ЯЁа-яё\-]+[\s,]*?)?"
    rf"(?:{_STREET_PREFIXES})"
    rf"\s+[А-ЯЁа-яё0-9][А-ЯЁа-яё0-9\s\-]{{1,60}}"
    rf"(?:,?\s*(?:д\.|дом)\s*\d+[А-Яа-яA-Za-z]?"
    rf"(?:(?:,?\s*(?:корп?\.|корпус)\s*\d+)?"
    rf"(?:,?\s*(?:кв\.|квартира|оф\.|офис)\s*\d+)?)?)?",
    re.IGNORECASE | re.UNICODE,
)
ALL_RULES.append(PDRule(
    category="address",
    pattern=_ADDRESS_STREET,
    description="Адрес (ул./пр./пер. ...)",
    priority=60,
))

# Адрес с указанием города + области
_ADDRESS_REGION = re.compile(
    r"(?:[А-ЯЁ][а-яё]+(?:ская|ский|ская|ная|ный)\s+обл\.?)"
    r"[\s,]+"
    r"(?:г\.|город)\s+[А-ЯЁ][а-яё]+",
    re.UNICODE,
)
ALL_RULES.append(PDRule(
    category="address",
    pattern=_ADDRESS_REGION,
    description="Адрес (область, город)",
    priority=55,
))

# Почтовый индекс с контекстом
_ADDRESS_ZIPCODE = re.compile(
    r"(?:индекс|почтовый\s+индекс)"
    r"[\s:]*"
    r"(\d{6})",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="address",
    pattern=_ADDRESS_ZIPCODE,
    description="Почтовый индекс с контекстом",
    priority=50,
    context_required=True,
))

# ===== 11. Email ============================================================

_EMAIL = re.compile(
    r"\b[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z0-9\-.]+\b",
)
ALL_RULES.append(PDRule(
    category="email",
    pattern=_EMAIL,
    description="Адрес электронной почты",
    priority=80,
))

# ===== 12. Телефон (phone) ==================================================

_PHONE = re.compile(
    r"(?:\+7|8)"
    r"[\s\-]*"
    r"\(?\d{3}\)?"
    r"[\s\-]*"
    r"\d{3}"
    r"[\s\-]*"
    r"\d{2}"
    r"[\s\-]*"
    r"\d{2}"
    r"\b",
)
ALL_RULES.append(PDRule(
    category="phone",
    pattern=_PHONE,
    description="Телефон РФ (+7/8)",
    priority=80,
))

# ===== 13. ИНН (inn) =======================================================

# ИНН физлица (12 цифр) с контекстом
_INN_12_CTX = re.compile(
    r"(?:инн|ИНН|inn)"
    r"[\s:]*"
    r"(\d{12})\b",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="inn",
    pattern=_INN_12_CTX,
    description="ИНН физлица (12 цифр) с контекстом",
    priority=85,
    context_required=True,
))

# ИНН юрлица (10 цифр) с контекстом
_INN_10_CTX = re.compile(
    r"(?:инн|ИНН|inn)"
    r"[\s:]*"
    r"(\d{10})\b",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="inn",
    pattern=_INN_10_CTX,
    description="ИНН юрлица (10 цифр) с контекстом",
    priority=80,
    context_required=True,
))

# ИНН без контекста (12 цифр) — ниже приоритет
_INN_12_BARE = re.compile(
    r"\b(\d{12})\b",
)
ALL_RULES.append(PDRule(
    category="inn",
    pattern=_INN_12_BARE,
    description="ИНН физлица (12 цифр) без контекста",
    priority=20,
))

# ===== 14. Номер карты (card_number) ========================================

_CARD_NUMBER = re.compile(
    r"\b([2-6]\d{3}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4})\b",
)
ALL_RULES.append(PDRule(
    category="card_number",
    pattern=_CARD_NUMBER,
    description="Номер банковской карты (16 цифр)",
    priority=85,
))

# ===== 15. CVV / CVC (cvv) =================================================

_CVV = re.compile(
    r"(?:CVV|CVC|CV2)"
    r"[\s/:]*"
    r"(\d{3})",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="cvv",
    pattern=_CVV,
    description="CVV/CVC код карты",
    priority=90,
    context_required=True,
))

# ===== 16. ПИН-код (pin) ===================================================

_PIN = re.compile(
    r"(?:пин[\s\-]*код|ПИН|PIN)"
    r"[\s/:]*"
    r"(\d{4})\b",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="pin",
    pattern=_PIN,
    description="ПИН-код карты",
    priority=90,
    context_required=True,
))

# ===== 17. Имя держателя карты (cardholder_name) ===========================

_CARDHOLDER = re.compile(
    r"(?:cardholder|держатель|имя\s+на\s+карте)"
    r"[\s/:]*"
    r"([A-Z][A-Z\s]{2,30})",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="cardholder_name",
    pattern=_CARDHOLDER,
    description="Имя держателя карты",
    priority=70,
    context_required=True,
))

# ===== 18. СНИЛС (snils) ===================================================

# Формат с дефисами: 123-456-789 00
_SNILS_DASHES = re.compile(
    r"\b(\d{3}-\d{3}-\d{3}\s?\d{2})\b",
)
ALL_RULES.append(PDRule(
    category="snils",
    pattern=_SNILS_DASHES,
    description="СНИЛС (NNN-NNN-NNN NN)",
    priority=85,
))

# Формат слитный (11 цифр) с контекстом
_SNILS_BARE = re.compile(
    r"(?:СНИЛС|снилс)"
    r"[\s:]*"
    r"(\d{11})\b",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="snils",
    pattern=_SNILS_BARE,
    description="СНИЛС слитный (11 цифр) с контекстом",
    priority=75,
    context_required=True,
))

# ===== 19. Полис ОМС (oms) =================================================

_OMS = re.compile(
    r"(?:ОМС|полис|медицинск(?:ий|ого)\s+полис(?:а)?)"
    r"[\s:]*"
    r"(\d{16})\b",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="oms",
    pattern=_OMS,
    description="Полис ОМС (16 цифр)",
    priority=80,
    context_required=True,
))

# ===== 20. Загранпаспорт (foreign_passport) ================================

_FOREIGN_PASSPORT = re.compile(
    r"(?:загранпаспорт|заграничн(?:ый|ого)\s+паспорт(?:а)?)"
    r"[\s:]*"
    r"(\d{2}\s?(?:№|No|N|#)?\s?\d{7})",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="foreign_passport",
    pattern=_FOREIGN_PASSPORT,
    description="Загранпаспорт",
    priority=85,
    context_required=True,
))

# ===== 21. Военный билет (military_id) =====================================

_MILITARY_ID = re.compile(
    r"(?:военный\s+билет|в/?б)"
    r"[\s:]*"
    r"([А-ЯA-Z]{2}\s?\d{7})",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="military_id",
    pattern=_MILITARY_ID,
    description="Военный билет",
    priority=80,
    context_required=True,
))
