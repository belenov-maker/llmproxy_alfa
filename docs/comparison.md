# Сравнительный архитектурный анализ: pd-proxy vs AlfaSonar

> Два решения хакатона по маскированию персональных данных (ПДн) при проксировании LLM-запросов.

---

## 1. Общая информация

| Параметр | **pd-proxy** (наш) | **AlfaSonar** (коллега) |
|----------|---------------------|--------------------------|
| Репозиторий | `belenov-maker/llmproxy_alfa` | `alfa-hackton` |
| Язык | Python 3.11 (FastAPI, Pydantic) | Go 1.23 (net/http) + Python 3.12 (FastAPI/gRPC) |
| Архитектура | Монолит: FastAPI + Gunicorn (4 workers) | Микросервисы: Go-gateway + Python NER + Redis |
| Docker | 1 контейнер (~2 GB с моделью) | 3 контейнера (Go + Python + Redis) |
| Лицензия | — | — |

---

## 2. Архитектура детекции

### pd-proxy: двухэшелонная гибридная система

```
Текст → Regex Engine (37 правил) → Dedup → Context Filter → Anti-FP → FastJev Judge (опц.) → Matches
```

- **Эшелон 1 (Regex)**: 37 скомпилированных regex-правил, покрывающих 21 категорию ПДн. Приоритетный порядок, контекстные правила (с обязательным контекстным словом) и бесконтекстные. Дедупликация перекрывающихся спанов.
- **Эшелон 2 (FastJev)**: Локальная LLM (Qwen3-0.6B, ~639 МБ, CPU inference через llama.cpp). Используется для anti-false-positive: Boolean-вопрос «Это персональные данные?» и Choice-вопрос «Какая категория?». Включается по `mode=full`.
- **Anti-FP**: Stop-lists (~60 известных персон, ~10 фикционных персонажей, ~15 орг-префиксов) + stem-matching + контекстная фильтрация PIN/CVV (только при наличии карты рядом).

### AlfaSonar: гибридный Go + Python NER

```
Текст → Go Regex (структурные типы) ──┐
                                       ├── Merge Spans → Маскирование
Текст → Python NER (Natasha) via gRPC ─┘
```

- **Go-слой (regex)**: Детектирует структурированные ПДн — даты, паспорта, ИНН, карты, телефоны, email, CVV/PIN, индексы. Luhn-валидация карт, INN-checksum (10/12 цифр).
- **Python-слой (Natasha NER)**: Детектирует семантические типы — ФИО (PER), адреса (LOC), места рождения, гражданство, органы выдачи. Обмен через gRPC (protobuf, таймаут 200мс).
- **Merge**: Спаны из Go и Python объединяются; при пересечении Go-regex имеет приоритет. Недопускаются overlaps.
- **Anti-FP**: Whitelist ~60 известных персон + контекстные маркеры (поэт/писатель/учёный/клиент/заёмщик) в окне ±5 токенов. Title-case re-run NER для дополнительной проверки.

### Сравнение подходов

| Аспект | pd-proxy | AlfaSonar |
|--------|----------|-----------|
| ФИО | Regex (паттерны «Фамилия Имя Отчество», инициалы) | Natasha NER (семантический разбор) |
| Адреса | Regex (паттерны «г. / ул. / пр-т / д. / кв.») | Natasha NER (LOC entities) |
| Места рождения | Regex (контекст «родился/рождения» + город) | Natasha NER (LOC + контекст) |
| Паспорт | Regex (серия + номер с/без контекста) | Regex (серия + номер) |
| ИНН | Regex (10/12 цифр + контекст) | Regex + checksum validation |
| Карты | Regex + Luhn | Regex + Luhn |
| Anti-FP для ФИО | Stop-lists + stem matching + FastJev judge | Whitelist + контекстные маркеры ±5 токенов |

**Вывод**: AlfaSonar сильнее в семантической детекции (ФИО/адреса) за счёт Natasha NER, но медленнее (gRPC overhead). pd-proxy быстрее (чистый regex), но менее точен для нетипичных форматов ФИО/адресов.

---

## 3. Категории ПДн

| # | Категория | pd-proxy | AlfaSonar | Примечание |
|---|-----------|----------|-----------|------------|
| 1 | ФИО | ✅ fio | ✅ FULL_NAME | Мы — regex, они — Natasha NER |
| 2 | Дата рождения | ✅ birth_date | ✅ BIRTH_DATE | Оба — regex |
| 3 | Место рождения | ✅ birth_place | ✅ BIRTH_PLACE | Мы — regex, они — NER |
| 4 | Паспорт (серия/номер) | ✅ passport | ✅ PASSPORT_SERIES_NUMBER | Оба — regex |
| 5 | Гражданство | ✅ citizenship | ✅ CITIZENSHIP | Мы — regex, они — NER |
| 6 | Орган выдачи | ✅ issuing_authority | ✅ PASSPORT_ISSUER | Мы — regex, они — NER |
| 7 | Код подразделения | ✅ subdivision_code | ✅ DEPARTMENT_CODE | Оба — regex |
| 8 | Дата выдачи | ✅ issue_date | ✅ PASSPORT_ISSUE_DATE | Оба — regex |
| 9 | Водительское удост-е | ✅ drivers_license | ✅ DRIVER_LICENSE | Оба — regex |
| 10 | Адрес | ✅ address | ✅ ADDRESS_* (6 полей) | Мы — 1 категория, они — 6 подполей |
| 11 | Email | ✅ email | ✅ EMAIL | Оба — regex |
| 12 | Телефон | ✅ phone | ✅ PHONE | Оба — regex |
| 13 | ИНН | ✅ inn | ✅ INN | Они + checksum |
| 14 | Карта | ✅ card_number | ✅ CARD_NUMBER | Оба + Luhn |
| 15 | CVV | ✅ cvv | ✅ CVV | Оба — context-dependent |
| 16 | PIN | ✅ pin | ✅ CARD_PIN | Оба — context-dependent |
| 17 | Владелец карты | ✅ cardholder_name | ✅ CARDHOLDER_NAME | Мы — regex, они — NER |
| 18 | СНИЛС | ✅ snils | ❌ — | **Только у нас** |
| 19 | ОМС | ✅ oms | ❌ — | **Только у нас** |
| 20 | Загранпаспорт | ✅ foreign_passport | ❌ — | **Только у нас** |
| 21 | Военный билет | ✅ military_id | ❌ — | **Только у нас** |
| 22 | Адрес (страна) | ⚠️ в составе address | ✅ ADDRESS_COUNTRY | Они — отдельное поле |
| 23 | Адрес (индекс) | ⚠️ в составе address | ✅ ADDRESS_INDEX | Они — отдельное поле |

**Итого**: pd-proxy — 21 категория, AlfaSonar — 22 категории (но без СНИЛС, ОМС, загранпаспорта, военного билета; зато с детализированным адресом).

---

## 4. Маскирование

| Аспект | pd-proxy | AlfaSonar |
|--------|----------|-----------|
| **Формат** | Placeholder: `[ФИО_1]`, `[ПАСПОРТ_1]` | Типизированный: `И. И. И.`, `45** ****56`, `a***@***.ru` |
| **Partial masking** | ✅ (настраивается в `systems.yaml`) | ✅ (встроено, типизированное) |
| **Нумерация** | Последовательная по категории: `[ФИО_1]`, `[ФИО_2]` | Без нумерации (каждый span маскируется индивидуально) |
| **Демаскирование** | `reverse_map` в хранилище: placeholder → original | State-machine: отправить mask с тем же payload_id → получить original |
| **Контекст** | Теряется (placeholder не сохраняет формат) | Сохраняется (видна длина, формат, первые/последние символы) |

**Вывод**: Типизированное маскирование AlfaSonar лучше для читаемости: жюри видит `И. И. И.` и понимает, что это ФИО, видит `+7 (***) ***-**-67` и понимает, что это телефон. Наши placeholder'ы `[ФИО_1]` менее наглядны, хотя гарантированно безопасны (утечка нулевых бит).

---

## 5. Идемпотентность

| Аспект | pd-proxy | AlfaSonar |
|--------|----------|-----------|
| **Хранилище** | In-memory dict (per-worker) | Redis (shared, persistent) |
| **Ключ** | SHA-256(payload) | payload_id (user-provided) |
| **TTL** | Настраивается (по умолч. 3600с) | 7 дней (168h) |
| **Multi-worker** | ❌ Не работает (каждый worker свой dict) | ✅ Redis общий для всех |
| **Race conditions** | Возможны (нет блокировки) | Защита через Redis SetNX |
| **Конфликты** | Нет обработки (повторный запрос = повторная обработка) | HTTP 409 при конфликте payload_id с другим payload |
| **Демаскирование** | Через reverse_map (GET /unmask/{payload_id}) | Через state-machine: POST /process с маской + тот же payload_id |

**Вывод**: Идемпотентность AlfaSonar значительно надёжнее: Redis shared store, SetNX для race-safe, 409 на конфликт payload_id. У нас — наивная in-memory реализация, ломающаяся при multi-worker Gunicorn.

---

## 6. API формат

### pd-proxy
```json
POST /process
{
  "payload": "Иванов Иван Иванович, паспорт 4510 123456",
  "payload_id": "req-001",
  "system_id": "default",
  "mode": "fast"
}
→ {
  "result": "[ФИО_1], паспорт [ПАСПОРТ_1]",
  "action": "masked",
  "stats": {
    "pd_found": 2,
    "categories": ["fio", "passport"],
    "regex_ms": 1.2,
    "jev_ms": 0,
    "total_ms": 2.5
  }
}
```

### AlfaSonar
```json
POST /process
{
  "payload": "Иванов Иван Иванович, паспорт 4510 123456",
  "payload_id": "req-001"
}
→ {
  "result": "И. И. И., паспорт 45** ****56"
}
```

**Различия**: pd-proxy возвращает подробную статистику (категории, время обработки), AlfaSonar — только результат. pd-proxy поддерживает `system_id` для мультитенантности и `mode` для выбора глубины анализа.

---

## 7. Производительность и нагрузка

| Метрика | pd-proxy | AlfaSonar |
|---------|----------|-----------|
| **RPS (измерено)** | ~9000 (regex only) | Не измерено |
| **p99 latency** | 25 мс | Не измерено (NER timeout 200мс) |
| **Rate limiting** | Token bucket (5000 RPS default) | Token bucket + semaphore (MaxInFlight=1024) |
| **429 + Retry-After** | ✅ | ✅ |
| **Max payload** | 100K tokens | 2 МБ (MAX_PAYLOAD_BYTES) |
| **Concurrency** | Gunicorn 4 workers + asyncio | Go goroutines + semaphore |

**Вывод**: pd-proxy на чистом regex показывает ~9000 RPS. AlfaSonar теоретически быстрее на Go-regex, но NER через gRPC (200мс timeout) может быть bottleneck при полной обработке. Go-gateway при NER_ENABLED=false должен показать сопоставимый или более высокий RPS.

---

## 8. Тестирование

| Метрика | pd-proxy | AlfaSonar |
|---------|----------|-----------|
| **Unit-тесты** | 223 (pytest) | Go tests + Python tests |
| **Integration тесты** | 718 (7 групп A-G, async aiohttp) | integration.py (459 строк, ~100 сценариев) |
| **Категории тестов** | A=прямые (21 кат.), B=граничные, C=anti-FP, D=комбо, E=идемпотентность, F=нагрузка, G=SpaCy | A-FN/BD/PP/CD/CV/PN/EM/PH/AD/CT/BP/PI (по категориям) + негативные + idempotency |
| **Отчёты** | TXT + JSON с known_limitations | stdout (pass/fail) |
| **Evaluation** | — | evaluate.py (precision/recall/F1 на аннотированных примерах) |
| **SpaCy верификация** | ✅ (33 теста SpaCy → regex cross-check) | ❌ |

**Вывод**: pd-proxy имеет значительно больше тестов (718 vs ~100) и более структурированные отчёты. AlfaSonar имеет evaluate.py для расчёта precision/recall — идея, которую стоит заимствовать.

---

## 9. Privacy и безопасность

| Аспект | pd-proxy | AlfaSonar |
|--------|----------|-----------|
| **Логирование значений ПДн** | ❌ Только категории | ❌ Только типы (явно отсечено в коде) |
| **Auth** | API Key middleware (опциональный) | ❌ Нет |
| **Метрики** | Prometheus `/metrics` | ❌ Нет |
| **UI** | ✅ Web-консоль `/ui/` | ❌ Нет |
| **Admin endpoints** | ✅ `/admin/systems`, `/admin/stats` | ❌ Нет |

---

## 10. Сводка сильных и слабых сторон

### pd-proxy — сильные стороны
1. ⚡ **Производительность**: 9000 RPS, p99=25мс (доказано бенчмарком)
2. 📦 **Простота деплоя**: 1 контейнер, без внешних зависимостей
3. 🎯 **Больше категорий**: СНИЛС, ОМС, загранпаспорт, военный билет
4. 🤖 **FastJev**: локальная LLM для anti-FP (уникальная фича)
5. 🧪 **Тесты**: 223 unit + 718 integration, SpaCy-верификация
6. 🖥️ **UI**: интерактивная web-консоль для тестирования
7. 📊 **Метрики**: Prometheus, admin endpoints
8. 🔐 **Auth**: API Key middleware

### pd-proxy — слабые стороны
1. ❌ **Идемпотентность**: in-memory, ломается при multi-worker
2. ❌ **Маскирование**: placeholder'ы менее наглядны, чем типизированные маски
3. ❌ **ИНН**: нет checksum-валидации (FP на случайных 10/12-значных числах)
4. ⚠️ **ФИО/адреса**: regex менее точен, чем NER для нетипичных форматов

### AlfaSonar — сильные стороны
1. 🧠 **NER**: Natasha для семантической детекции ФИО/адресов
2. 🔒 **Идемпотентность**: Redis SetNX state-machine, race-safe, 409 на конфликт
3. 🎭 **Маскирование**: типизированное, читаемое, сохраняет контекст
4. ✅ **ИНН checksum**: валидация контрольных разрядов
5. 📏 **Контекст-фильтр**: маркеры ±5 токенов для anti-FP ФИО
6. 🔬 **Evaluation**: precision/recall/F1 на аннотированных данных

### AlfaSonar — слабые стороны
1. ❌ **Нет СНИЛС, ОМС, загранпаспорта, военного билета**
2. ❌ **Сложнее деплой**: 3 контейнера + Redis
3. ❌ **Нет UI, нет метрик, нет auth**
4. ⚠️ **NER latency**: gRPC-запрос к Python NER добавляет ~50-200мс
5. ⚠️ **Меньше тестов**: ~100 integration vs 718

---

## 11. Что заимствовать из AlfaSonar

| # | Идея | Приоритет | Оценка трудозатрат |
|---|------|-----------|--------------------|
| 1 | **INN checksum валидация** | 🔴 Высокий | 30 мин (добавить `_inn_checksum()` в `detector.py`) |
| 2 | **Типизированное маскирование** | 🟡 Средний | 1-2 ч (новый режим в `masker.py`) |
| 3 | **Расширенные контекстные маркеры anti-FP** | 🟡 Средний | 30 мин (расширить stop-lists + окно контекста) |
| 4 | **Evaluation (precision/recall)** | 🟢 Низкий | 1 ч (скрипт по аналогии с их `evaluate.py`) |
| 5 | **Redis для идемпотентности** | 🟢 Низкий | 2-3 ч (замена InMemory → Redis) |

---

## 12. Рекомендации

1. **Быстрые победы** (до финала хакатона): INN checksum + расширение anti-FP стоп-листов.
2. **Среднесрочные** (если есть время): типизированное маскирование — самый заметный визуальный эффект для жюри.
3. **Долгосрочные** (после хакатона): Redis для идемпотентности, evaluation framework, NER integration.
