# PD-Proxy — Модуль безопасности персональных данных

> Прокси-сервис для идентификации, маскирования и демаскирования персональных данных (ПДн) в запросах к LLM.  
> **Хакатон AlfaGen 2026**

## Ключевые возможности

- **21 категория ПДн**: ФИО, паспорт, СНИЛС, ИНН, телефон, email, банковские карты (Luhn), CVV, ПИН, адрес, дата рождения, водительское удостоверение, загранпаспорт, ОМС, военный билет и др.
- **Трёхэшелонная архитектура**: regex (Эшелон 1) + Natasha NER (Эшелон 1.5, семантический anti-FP) + FastJev Qwen3-0.6B (Эшелон 2)
- **LLM-прокси**: маскирование → LLM (DeepSeek V4 Flash) → демаскирование — ПДн **никогда не покидают периметр**
- **Производительность**: 9000+ RPS, p99 < 25 мс (regex-режим)
- **Гибкая настройка**: конфигурация систем через YAML без правки кода
- **Расширенные сценарии**: частичное маскирование, контекстная фильтрация (ПИН без карты = не ПДн)

## Quick Start

### Локальный запуск (рекомендуется для демо)

```bash
# 1. Установить зависимости
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Запустить сервис
uvicorn app.main:app --host 0.0.0.0 --port 8080

# 3. Проверить
curl http://localhost:8080/health
```

### Docker

```bash
docker compose up -d
curl http://localhost:8080/health
```

### Production (gunicorn, multi-worker)

```bash
gunicorn app.main:app -c gunicorn.conf.py
```

## API

### `POST /process` — Маскирование/демаскирование

**Маскирование** (первый запрос с новым `payload_id`):

```bash
curl -X POST http://localhost:8080/process \
  -H "Content-Type: application/json" \
  -d '{
    "payload": "Клиент Иванов Иван Иванович, паспорт 4510 123456, тел +7(999)888-77-66, email ivan@mail.ru, ИНН 770123456789",
    "payload_id": "req-001"
  }'
```

Ответ:
```json
{
  "result": "Клиент [FIO_1], паспорт [PASSPORT_1], тел [PHONE_1], email [EMAIL_1], ИНН [INN_1]",
  "payload_id": "req-001",
  "action": "masked",
  "stats": {
    "pd_found": 5,
    "categories": ["fio", "passport", "phone", "email", "inn"],
    "regex_ms": 0.08,
    "jev_ms": 0.0,
    "total_ms": 0.35
  }
}
```

**Демаскирование** (повторный запрос с тем же `payload_id`, другой payload):

```bash
curl -X POST http://localhost:8080/process \
  -H "Content-Type: application/json" \
  -d '{
    "payload": "Одобрено для [FIO_1], номер дела [PASSPORT_1]",
    "payload_id": "req-001"
  }'
```

Ответ:
```json
{
  "result": "Одобрено для Иванов Иван Иванович, номер дела 4510 123456",
  "payload_id": "req-001",
  "action": "unmasked"
}
```

**Идемпотентность** (тот же payload_id + тот же payload):

```bash
# Повторный вызов с идентичными данными → кэшированный результат
curl -X POST http://localhost:8080/process \
  -H "Content-Type: application/json" \
  -d '{"payload": "Иванов Иван Иванович", "payload_id": "req-001"}'
# → action: "cached"
```

### `POST /proxy` — LLM-прокси (маскирование → LLM → демаскирование)

```bash
curl -X POST http://localhost:8080/proxy \
  -H "Content-Type: application/json" \
  -d '{
    "payload": "Составь ответ клиенту Иванову Ивану Ивановичу, тел +79998887766",
    "payload_id": "proxy-001",
    "llm_prompt": "Напиши вежливый ответ клиенту"
  }'
```

> ⚠️ Для работы `/proxy` требуется API-ключ LLM (переменная `PD_PROXY_LLM_API_KEY`).

### `GET /health` — Проверка здоровья

```bash
curl http://localhost:8080/health
# → {"status": "ok", "version": "0.1.0"}
```

### `GET /metrics` — Prometheus-метрики

```bash
curl http://localhost:8080/metrics
# → pd_proxy_requests_total{action="masked",system_id="default"} 42.0
#   pd_proxy_request_latency_seconds_bucket{...}
#   pd_proxy_pd_detected_total{category="fio"} 15.0
```

### `GET /admin/systems` — Конфигурация систем

```bash
curl http://localhost:8080/admin/systems
```

## Режимы работы

| Режим | Описание | Latency | Применение |
|-------|----------|---------|------------|
| `fast` | Только regex-движок | < 1 мс | Нагрузочное тестирование, продакшн |
| `full` | Regex + FastJev (anti-FP) | 50-200 мс | Высокая точность, демо |

Режим настраивается per-система в `config/systems.yaml`:

```yaml
systems:
  billing:
    mode: fast
    masking_style: placeholder
  crm:
    mode: full
    masking_style: partial
```

## Категории ПДн (21)

| # | Категория | Пример | Regex |
|---|-----------|--------|-------|
| 1 | ФИО | Иванов Иван Иванович | ✅ |
| 2 | Дата рождения | 15.03.1990 | ✅ |
| 3 | Место рождения | г. Москва | ✅ |
| 4 | Паспорт РФ | 4510 123456 | ✅ |
| 5 | Гражданство | гражданство: РФ | ✅ |
| 6 | Орган выдачи | ОВД района Тверской | ✅ |
| 7 | Код подразделения | 770-001 | ✅ |
| 8 | Дата выдачи | выдан 01.01.2020 | ✅ |
| 9 | Водительское удостоверение | 77 АА 123456 | ✅ |
| 10 | Адрес | ул. Пушкина, д. 10, кв. 5 | ✅ |
| 11 | Email | ivan@mail.ru | ✅ |
| 12 | Телефон | +7 (999) 888-77-66 | ✅ |
| 13 | ИНН | 770123456789 | ✅ |
| 14 | Банковская карта | 4276 1234 5678 9010 (Luhn) | ✅ |
| 15 | CVV | CVV 123 (контекстно) | ✅ |
| 16 | ПИН-код | ПИН 1234 (контекстно) | ✅ |
| 17 | Имя держателя карты | IVAN IVANOV | ✅ |
| 18 | СНИЛС | 123-456-789 00 | ✅ |
| 19 | ОМС | полис ОМС 1234567890123456 | ✅ |
| 20 | Загранпаспорт | 51 1234567 | ✅ |
| 21 | Военный билет | АА 1234567 | ✅ |

## Anti-FP (защита от ложных срабатываний)

- **Natasha NER (ORG)**: ФИО внутри организации («ООО Ромашка») → не маскируется
- **Известные личности**: «Александр Пушкин» → не маскируется
- **Контекст карты**: ПИН/CVV маскируются только рядом с номером карты
- **FastJev (Эшелон 2)**: Qwen3-0.6B классифицирует спорные случаи через logit-scoring
- **Контрольные числа**: Luhn для банковских карт, контрольные цифры для СНИЛС

## Производительность

| Метрика | Значение | Критерий | Статус |
|---------|----------|----------|--------|
| **RPS** | 9 009 | ≥ 1 000 | ✅ |
| **p99 latency** | 24.9 ms | ≤ 1 000 ms | ✅ |
| p50 latency | 10.5 ms | — | — |
| Ошибки | 0.17% | < 1% | ✅ |

> Тест: 100 VU, 30 секунд, 273 026 запросов. Режим `fast` (regex-only).  
> Сервер: gunicorn + uvicorn, 8 workers, Apple Silicon.

## Конфигурация

Все параметры настраиваются через переменные окружения с префиксом `PD_PROXY_`:

| Переменная | Описание | По умолчанию |
|-----------|----------|-------------|
| `PD_PROXY_PORT` | Порт сервиса | 8080 |
| `PD_PROXY_WORKERS` | Число worker'ов gunicorn | CPU×2+1 (макс 8) |
| `PD_PROXY_AUTH_ENABLED` | Включить API-key аутентификацию | false |
| `PD_PROXY_NLP_ENABLED` | Включить Natasha NER (Эшелон 1.5) | true |
| `PD_PROXY_JEV_ENABLED` | Включить FastJev (Эшелон 2) | true |
| `PD_PROXY_JEV_MODEL` | Модель FastJev | Qwen/Qwen3-0.6B |
| `PD_PROXY_STORAGE_TTL_SECONDS` | TTL маппингов в памяти | 3600 |
| `PD_PROXY_STORAGE_MAX_SIZE` | Макс. размер хранилища | 100 000 |
| `PD_PROXY_LLM_BASE_URL` | URL LLM API | — |
| `PD_PROXY_LLM_API_KEY` | API-ключ LLM | — |
| `PD_PROXY_LLM_MODEL` | Модель LLM | deepseek-ai/DeepSeek-V4-Flash-0731 |
| `PD_PROXY_LOG_LEVEL` | Уровень логирования | info |

## Структура проекта

```
pd-proxy/
├── app/
│   ├── engine/
│   │   ├── detector.py        # Оркестрация детекции
│   │   ├── regex_rules.py     # 21 категория regex-правил
│   │   ├── nlp_detector.py    # Natasha NER — Эшелон 1.5 (PER/LOC/ORG)
│   │   ├── jev_judge.py       # FastJev (Qwen3-0.6B) — Эшелон 2
│   │   ├── masker.py          # Маскирование → плейсхолдеры
│   │   └── unmasker.py        # Демаскирование
│   ├── proxy/
│   │   └── llm_proxy.py       # LLM-прокси (маскирование→LLM→демаскирование)
│   ├── security/
│   │   ├── auth.py            # API-key middleware
│   │   └── rate_limit.py      # Token bucket rate limiter
│   ├── storage/
│   │   └── memory.py          # In-memory хранилище маппингов (TTL+LRU)
│   ├── config.py              # Конфигурация (Pydantic Settings)
│   ├── main.py                # FastAPI-приложение
│   ├── metrics.py             # Prometheus-метрики
│   └── models.py              # Pydantic-модели запросов/ответов
├── config/
│   └── systems.yaml           # Конфигурация систем-потребителей
├── tests/                     # 190 тестов
├── bench/                     # Нагрузочные тесты + отчёт
├── docs/
│   └── architecture.md        # Архитектура (Mermaid)
├── Dockerfile
├── docker-compose.yml
├── gunicorn.conf.py
└── requirements.txt
```

## Тесты

```bash
# Запуск всех тестов
pytest tests/ -v

# Быстрая проверка
pytest tests/ -x -q
# → 190 passed in 0.9s
```

## Ограничения

1. **In-memory storage**: маппинги хранятся в памяти и теряются при перезапуске. Для продакшна рекомендуется Redis/PostgreSQL.
2. **Однопроцессный FastJev**: модель загружается в каждый worker. Для экономии RAM — отдельный inference-сервис.
3. **Regex FIO**: русские ФИО могут давать FP на географические названия. FastJev снижает, но не устраняет полностью.
4. **Нет шифрования маппингов**: в продакшне маппинги (оригинал↔плейсхолдер) должны шифроваться at-rest.

## Roadmap

- [ ] Persistent storage (Redis / PostgreSQL)
- [ ] Шифрование маппингов AES-256
- [ ] Стриминг обработки для текстов > 1MB
- [ ] Web UI для администрирования
- [ ] ONNX-оптимизация FastJev для GPU
- [ ] OpenTelemetry distributed tracing

## Лицензия

Разработано для хакатона AlfaGen 2026.
