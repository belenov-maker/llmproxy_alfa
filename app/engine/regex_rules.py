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
    use_group: int = 0  # Какую группу использовать для value/span (0 = весь match)


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
# Слово кириллицей (любой регистр, 2+ букв) — для lowercase ФИО
_CYR_WORD_ANY = r"[А-ЯЁа-яё]{3,}"

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

# Lowercase ФИО с контекстом: «фио: иванов иван иванович»
_FIO_LOWER_CTX = re.compile(
    r"(?:фио|ф\.?и\.?о\.?|клиент|заёмщик|заемщик|владелец|получатель|абонент|пациент|заявитель)"
    r"[\s:]+"
    rf"({_CYR_WORD_ANY}(?:-{_CYR_WORD_ANY})?)"
    rf"\s+"
    rf"({_CYR_WORD_ANY})"
    rf"(?:\s+({_CYR_WORD_ANY}))?",
    re.IGNORECASE | re.UNICODE,
)
ALL_RULES.append(PDRule(
    category="fio",
    pattern=_FIO_LOWER_CTX,
    description="ФИО в нижнем регистре (с контекстом)",
    priority=75,
    context_required=True,
))

# ===== 2. Дата рождения (birth_date) =======================================

# С контекстом
_BIRTH_DATE_CTX = re.compile(
    r"(?:дата\s+рожд(?:ения|\.)?|д\.?\s?р\.?|родил(?:ся|ась)|рождён(?:а)?|born|ДР|р\.)"
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
    r"(?:дата\s+рожд(?:ения|\.)?|д\.?\s?р\.?|родил(?:ся|ась)|рождён(?:а)?|born|ДР|р\.)"
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

# Год рождения: «год рождения 1990»
_BIRTH_YEAR = re.compile(
    r"(?:год\s+рождения)"
    r"[\s:]*"
    r"(\d{4})\b",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="birth_date",
    pattern=_BIRTH_YEAR,
    description="Год рождения",
    priority=60,
    context_required=True,
))

# Дата рождения с постфиксом: «01.07.1980 г.р.»
_BIRTH_DATE_SUFFIX = re.compile(
    r"(\d{1,2}[./-]\d{1,2}[./-]\d{4})\s*г\.?\s*р\.?",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="birth_date",
    pattern=_BIRTH_DATE_SUFFIX,
    description="Дата рождения (постфикс г.р.)",
    priority=80,
    context_required=True,
))

# ISO-формат даты рождения с контекстом: «дата рождения 1990.01.15», «born 1990-01-15»
_BIRTH_DATE_ISO = re.compile(
    r"(?:дата\s+рожд(?:ения|\.)?|д\.?\s?р\.?|родил(?:ся|ась)|рождён(?:а)?|born|ДР|р\.)"
    r"[\s:]*"
    r"(\d{4}[./-]\d{1,2}[./-]\d{1,2})",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="birth_date",
    pattern=_BIRTH_DATE_ISO,
    description="Дата рождения (ISO yyyy.mm.dd / yyyy-mm-dd с контекстом)",
    priority=80,
    context_required=True,
))

# ===== 3. Место рождения (birth_place) =====================================

_BIRTH_PLACE = re.compile(
    r"(?:место\s+рождения|родил(?:ся|ась)\s+в|уроженец|уроженка)"
    r"[\s:]*"
    r"(.{5,80}?)(?=[,;.\n]|$)",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="birth_place",
    pattern=_BIRTH_PLACE,
    description="Место рождения",
    priority=70,
    context_required=True,
))

# Место рождения: «Родилась 10.12.1995 в г. Новосибирске» (дата между глаголом и местом)
_BIRTH_PLACE_WITH_DATE = re.compile(
    r"(?:родил(?:ся|ась))\s+\d{1,2}[./-]\d{1,2}[./-]\d{4}\s+в\s+"
    r"(.{3,60}?)(?=[,;.\n]|$)",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="birth_place",
    pattern=_BIRTH_PLACE_WITH_DATE,
    description="Место рождения (после даты)",
    priority=72,
    context_required=True,
    use_group=1,
))

# ===== 4. Паспорт (passport) ===============================================

# С контекстом: «паспорт 4509 123456», «паспорт серия 4525 номер 345678»
_PASSPORT_CTX = re.compile(
    r"(?:паспорт(?:а|ные\s+данные)?(?:\s+гражданина\s+РФ)?|серия(?:\s+и\s+номер)?|passport)"
    r"[\s:,.]*"
    r"(?:серия\s+)?"
    r"(\d{2}\s*\d{2})"
    r"\s*(?:номер|№)?\s*"
    r"(\d{6})",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="passport",
    pattern=_PASSPORT_CTX,
    description="Паспорт с контекстным словом",
    priority=90,
    context_required=True,
))

# Слитный формат (10 цифр) с контекстом: «паспорт 4510123456»
_PASSPORT_SOLID = re.compile(
    r"(?:паспорт(?:а|ные\s+данные)?|passport)"
    r"[\s:,.]*"
    r"(\d{10})\b",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="passport",
    pattern=_PASSPORT_SOLID,
    description="Паспорт слитный (10 цифр) с контекстом",
    priority=85,
    context_required=True,
))

# Без контекста: формат «4509 123456» (4 + пробелы + 6)
_PASSPORT_NO_CTX = re.compile(
    r"\b(\d{4})\s+(\d{6})\b",
)
ALL_RULES.append(PDRule(
    category="passport",
    pattern=_PASSPORT_NO_CTX,
    description="Паспорт без контекста (NNNN NNNNNN)",
    priority=30,
))

# ===== 5. Гражданство (citizenship) ========================================

_CITIZENSHIP = re.compile(
    r"(?:гражданство|гражданин|гражданка|подданство|подданный|подданная)"
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
    r"(?:(?:кем\s+)?выдан[оа]?|орган(?:\s+выдачи)?)"
    r"[\s:]*"
    r"((?:ОВД|[ОУ]?ФМС|УФМС|ОУФМС|МВД|ГУ\s+МВД|УМВД|ТП"
    r"|[Оо]тдел(?:ом|ением|ение|а)?|[Уу]правлени(?:ем|е|я)?)"
    r".{5,120}?)"
    r"(?:\d{2}\.\d{2}\.\d{4}|код\s+подразделения|к/п|[,;.]|\s*$)",
    re.IGNORECASE | re.MULTILINE,
)
ALL_RULES.append(PDRule(
    category="issuing_authority",
    pattern=_ISSUING_AUTHORITY,
    description="Орган выдачи документа",
    priority=60,
    context_required=True,
    use_group=1,
))

# Орган выдачи — косвенная форма: «отделом УФМС», «отделением МВД»
_ISSUING_AUTHORITY_INSTR = re.compile(
    r"\b((?:[Оо]тдел(?:ом|ением)?|[Уу]правлением)"
    r"\s+(?:[ОУ]?ФМС|УФМС|ОУФМС|МВД|ОВД|ГУ\s+МВД|УМВД)"
    r"(?:\s+.{2,60}?)?)" 
    r"(?=[,;.]|\s+к/?[\sп]|$)",
    re.IGNORECASE | re.MULTILINE,
)
ALL_RULES.append(PDRule(
    category="issuing_authority",
    pattern=_ISSUING_AUTHORITY_INSTR,
    description="Орган выдачи (косвенная форма)",
    priority=58,
    context_required=False,
))

# Орган выдачи — короткая форма: «ГУ МВД России по г. Москве» без «выдан»
_ISSUING_AUTHORITY_SHORT = re.compile(
    r"\b((?:ГУ\s+МВД|УМВД|МВД|ОВД|[ОУ]?ФМС|УФМС|ОУФМС)"
    r"\s+(?:России\s+)?(?:по\s+)?(?:г\.|гор\.?)\s+[А-ЯЁ][а-яё]+(?:\s+[а-яё]+)*)",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="issuing_authority",
    pattern=_ISSUING_AUTHORITY_SHORT,
    description="Орган выдачи (краткая форма)",
    priority=55,
    context_required=False,
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
    r"(?:дата\s+выдачи(?:\s+\w+)?|выдан[оа]?)"
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

# Дата выдачи — дата рядом с «выдан» (дата после органа)
# use_group=1 — в detector используется group(1) вместо group(0)
_ISSUE_DATE_AFTER_ORG = re.compile(
    r"(?:выдан[оа]?)\s+"
    r"(?:[А-ЯЁа-яё0-9\s.,\-/()]+?)\s+"
    r"(\d{1,2}[./-]\d{1,2}[./-]\d{4})",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="issue_date",
    pattern=_ISSUE_DATE_AFTER_ORG,
    description="Дата выдачи (после органа)",
    priority=65,
    context_required=True,
    use_group=1,  # Только дата, не орган
))

# Дата выдачи текстом: «выдано 5 марта 2010 года»
_ISSUE_DATE_TEXT = re.compile(
    r"(?:дата\s+выдачи(?:\s+\w+)?|выдан[оа]?)"
    r"[\s:]*"
    rf"(\d{{1,2}}\s+{_MONTHS_RU}\s+\d{{4}}(?:\s*(?:г\.?|года?))?)",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="issue_date",
    pattern=_ISSUE_DATE_TEXT,
    description="Дата выдачи документа (текстом)",
    priority=70,
    context_required=True,
))

# ===== 9. Водительское удостоверение (drivers_license) ======================

_DRIVERS_LICENSE = re.compile(
    r"(?:водительск(?:ое\s+удостоверение|(?:ого\s+удостоверения)|ие\s+права)|удостоверение\s+водителя"
    r"|в/?у\b|ВУ\b|права\b)"
    r"(?:\s+сери[ияей]+)?"
    r"[\s:№#]*"
    r"(?:(?:серия\s+)?\d{2}\s+\d{2}\s+(?:(?:номер|№)\s*)?\d{6}"
    r"|(?:серия\s+)?\d{2}\s*\d{2}\s*(?:(?:номер|№)\s*)?\d{6}"
    r"|\d{2}\s?[А-ЯA-Z]{2}\s?\d{6}"
    r"|\d{4}\s?\d{6})",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="drivers_license",
    pattern=_DRIVERS_LICENSE,
    description="Водительское удостоверение",
    priority=92,
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

# Адрес: Название + тип улицы (обратный порядок, напр. "Красный проспект, д. 50")
_ADDRESS_STREET_REV = re.compile(
    rf"(?:(?:г\.|город)\s+[А-ЯЁа-яё\-]+[\s,]*?)?"
    rf"[А-ЯЁ][а-яё]+(?:\s+[а-яё]+)?\s+(?:проспект|бульвар|шоссе|набережная|площадь|переулок)"
    rf"(?:,?\s*(?:д\.|дом)\s*\d+[А-Яа-яA-Za-z]?"
    rf"(?:(?:,?\s*(?:корп?\.| корпус)\s*\d+)?"
    rf"(?:,?\s*(?:кв\.|квартира|оф\.|офис)\s*\d+)?)?)?" ,
    re.IGNORECASE | re.UNICODE,
)
ALL_RULES.append(PDRule(
    category="address",
    pattern=_ADDRESS_STREET_REV,
    description="Адрес (Название + тип улицы)",
    priority=58,
))

# Адрес с контекстным словом: "адрес: г. Город, ..."
_ADDRESS_CTX = re.compile(
    r"(?:адрес|проживает|зарегистрирован[аы]?)\s*[:.]?\s*"
    r"((?:г\.|город)\s+[А-ЯЁ][а-яё\-]+.{5,100}?)"
    r"(?=\s*$|\n|\s*(?:Тел|тел|Телефон|телефон|Email|email|E-mail|Карта|карта|Гражданство|гражданство|СНИЛС|ИНН))",
    re.IGNORECASE | re.UNICODE,
)
ALL_RULES.append(PDRule(
    category="address",
    pattern=_ADDRESS_CTX,
    description="Адрес с контекстным словом",
    priority=62,
    context_required=True,
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

# Адрес: индекс + город
_ADDRESS_ZIP_CITY = re.compile(
    r"\b(\d{6}),?\s*(?:г\.|город)\s+[А-ЯЁ][а-яё]+(?:\s*,\s*.{5,80})?",
    re.UNICODE,
)
ALL_RULES.append(PDRule(
    category="address",
    pattern=_ADDRESS_ZIP_CITY,
    description="Адрес (индекс + город)",
    priority=65,
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
    r"(?:\s+\w+)?"
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
    r"(?:\s+\w+)?"
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
    r"(?:CVV2?|CVC2?|CV2|код\s+безопасности)"
    r"[\s/:]*"
    r"(\d{3})\b",
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
    r"(?:(?:пин|PIN)[\s\-]*код|ПИН|PIN)"
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
    r"(?:cardholder|держатель|имя\s+на\s+карте|карта)"
    r"[\s/:]*"
    r"([A-Z]{2,20}(?:\s+[A-Z]{2,20}){1,2}(?:\s+[A-Z])?)",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="cardholder_name",
    pattern=_CARDHOLDER,
    description="Имя держателя карты",
    priority=70,
    context_required=True,
))

# Имя держателя (латиница без контекста) — low priority
_CARDHOLDER_BARE = re.compile(
    r"\b([A-Z]{2,20}\s+[A-Z]{2,20}(?:\s+[A-Z])?)\b",
)
ALL_RULES.append(PDRule(
    category="cardholder_name",
    pattern=_CARDHOLDER_BARE,
    description="Имя держателя карты (латиница без контекста)",
    priority=25,
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
    r"(?:"
        r"(?:полис|номер)\s+(?:обязательного\s+медицинского\s+страхования|ОМС)"
        r"|ОМС"
        r"|медицинск(?:ий|ого)\s+полис(?:а)?"
        r"|мед\.\s*полис"
        r"|номер\s+полиса\s+ОМС"
        r"|полис\s+ОМС"
        r"|номер\s+ОМС"
        r"|полис"
    r")"
    r"(?:\s+(?:нового\s+образца|пациента|работника|сотрудника))?"
    r"[\s:№#]*"
    r"(\d{16})\b",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="oms",
    pattern=_OMS,
    description="Полис ОМС (16 цифр)",
    priority=95,
    context_required=True,
))

# ===== 20. Загранпаспорт (foreign_passport) ================================

_FOREIGN_PASSPORT = re.compile(
    r"(?:загран(?:ичн(?:ый|ого))?\s*\.?\s*паспорт(?:а)?|загранпаспорт|загран\b|з/п\b)"
    r"(?:\s+(?:РФ|нового\s+образца))?"
    r"[\s:№#]*"
    r"(?:(?:серия\s+)?\d{2}\s*(?:(?:номер|№|No|N|#)\s*)?\d{7}"
    r"|\d{2}\s?\d{7})",
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
    r"(?:военн(?:ый|ого)\s+билет(?:а)?|воен\.\s*билет|в/?б)"
    r"[\s:№#]*"
    r"(?:сери[яи]\s+)?"
    r"[А-ЯA-Z]{2}"
    r"\s*(?:(?:номер|№)\s*)?"
    r"\d{7}",
    re.IGNORECASE,
)
ALL_RULES.append(PDRule(
    category="military_id",
    pattern=_MILITARY_ID,
    description="Военный билет",
    priority=80,
    context_required=True,
))
