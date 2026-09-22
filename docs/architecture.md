# Архитектура PD-Proxy

## Общая схема

```mermaid
flowchart TB
    subgraph Клиенты
        A[Система-потребитель<br>CRM / Billing / HR]
    end

    subgraph PD-Proxy
        direction TB
        GW[API Gateway<br>FastAPI + Auth + Rate Limit]
        
        subgraph Pipeline["Двухэшелонный pipeline"]
            direction TB
            E1[Эшелон 1<br>Regex Engine<br>21 категория · &lt;1мс]
            E2[Эшелон 2<br>FastJev · Qwen3-0.6B<br>Anti-FP · 50-200мс]
            E1 -->|regex matches| E2
        end
        
        MSK[Masker<br>Типизированные плейсхолдеры]
        UMSK[Unmasker<br>Восстановление по маппингу]
        STORE[(In-Memory Storage<br>payload_id → mapping<br>TTL + LRU)]
        
        GW --> Pipeline
        Pipeline --> MSK
        MSK --> STORE
        STORE --> UMSK
    end

    subgraph "LLM Provider"
        LLM[DeepSeek V4 Flash<br>AlfaGen API]
    end

    A -->|POST /process| GW
    A -->|POST /proxy| GW
    GW -->|маскированный текст| LLM
    LLM -->|ответ| UMSK
    UMSK -->|демаскированный ответ| A
```

## Поток обработки `/process`

```mermaid
sequenceDiagram
    participant C as Клиент
    participant API as FastAPI
    participant S as Storage
    participant R as Regex Engine
    participant J as FastJev
    participant M as Masker

    C->>API: POST /process {payload, payload_id}
    API->>S: get(payload_id)
    
    alt payload_id существует, payload совпадает
        S-->>API: cached result
        API-->>C: {result, action: "cached"}
    else payload_id существует, payload другой
        S-->>API: reverse_map
        API->>API: unmask(payload, reverse_map)
        API-->>C: {result, action: "unmasked"}
    else payload_id новый
        S-->>API: null
        API->>R: detect(text)
        R-->>API: List[PDMatch]
        
        opt mode == "full"
            API->>J: verify_matches(text, matches)
            J-->>API: filtered matches
        end
        
        API->>M: mask_text(text, matches)
        M-->>API: {masked_text, forward_map, reverse_map}
        API->>S: put(entry)
        API-->>C: {result, action: "masked", stats}
    end
```

## Поток обработки `/proxy`

```mermaid
sequenceDiagram
    participant C as Клиент
    participant API as FastAPI
    participant R as Regex Engine
    participant M as Masker
    participant LLM as DeepSeek V4
    participant U as Unmasker

    C->>API: POST /proxy {payload, payload_id, llm_prompt}
    API->>R: detect(payload)
    R-->>API: matches
    API->>M: mask_text(payload, matches)
    M-->>API: masked_text + reverse_map
    
    Note over API,LLM: ПДн НЕ покидают периметр
    API->>LLM: {masked_text + llm_prompt}
    LLM-->>API: llm_response
    
    API->>U: unmask(llm_response, reverse_map)
    U-->>API: original_response
    API-->>C: {result, masked_input, stats}
```

## Компоненты

### Эшелон 1: Regex Engine (`app/engine/regex_rules.py`)

- **21 категория** regex-правил для русскоязычных ПДн
- Скомпилированные паттерны (`re.compile`, `re.IGNORECASE`)
- Контрольные числа: Luhn для карт, валидация СНИЛС
- Контекстная фильтрация: ПИН/CVV только рядом с картой
- **Производительность**: ~0.09 мс на типовой текст

### Эшелон 2: FastJev (`app/engine/jev_judge.py`)

- **Модель**: Qwen3-0.6B (GGUF Q8_0, 639 МБ)
- **Бэкенд**: llama-cpp-python (CPU inference)
- **API**: `FastJev.decide_many()` — батч-обработка
- **Логика**: Boolean-вопросы + logit-scoring
- **Fail-open**: при ошибке FastJev → regex-результат принимается как есть

### Masker (`app/engine/masker.py`)

- Типизированные плейсхолдеры: `[FIO_1]`, `[PASSPORT_1]`, `[PHONE_1]`
- Стили маскирования: `placeholder`, `partial` (часть данных видна)
- Детерминированная нумерация

### Storage (`app/storage/memory.py`)

- In-memory dict: `payload_id → MaskingEntry`
- TTL-based expiration (по умолчанию 1 час)
- LRU eviction при превышении `max_size`
- Потокобезопасный (thread-safe)

### Security

| Компонент | Описание |
|-----------|----------|
| API Key Auth | Middleware, ключи в `systems.yaml`, включается через `PD_PROXY_AUTH_ENABLED` |
| Rate Limiter | Token bucket, Pure ASGI middleware, 5000 rps default |
| Structured Logging | JSON-формат, **ПДн никогда не логируются** |
| Prometheus Metrics | `pd_proxy_requests_total`, `pd_proxy_request_latency_seconds`, `pd_proxy_pd_detected_total` |

## Режимы работы

```mermaid
graph LR
    subgraph "mode=fast (RPS 9000+)"
        F1[Regex] --> F2[Masker]
    end
    
    subgraph "mode=full (high accuracy)"
        A1[Regex] --> A2[FastJev] --> A3[Masker]
    end
```

| Режим | Pipeline | Latency | Применение |
|-------|----------|---------|------------|
| `fast` | Regex → Masker | < 1 мс | Нагрузочный тест, продакшн |
| `full` | Regex → FastJev → Masker | 50-200 мс | Максимальная точность |

## Конфигурация систем

Каждая система-потребитель настраивается в `config/systems.yaml`:

```yaml
systems:
  billing:
    mode: fast
    masking_style: placeholder
    api_key: "sk-billing-..."
  crm:
    mode: full
    masking_style: partial
    api_key: "sk-crm-..."
```

## Ограничения и план развития

### Текущие ограничения

1. **In-memory storage** — данные теряются при перезапуске
2. **Однопроцессный FastJev** — модель загружается в каждый worker
3. **Regex FIO** — возможны FP на географические названия
4. **Нет шифрования** маппингов at-rest

### Roadmap

| Приоритет | Улучшение | Описание |
|-----------|----------|----------|
| P0 | Redis storage | Persistent маппинги, кластеризация |
| P0 | Шифрование маппингов | AES-256 для forward/reverse maps |
| P1 | FastJev inference server | Отдельный сервис, shared GPU |
| P1 | Стриминг | Обработка текстов > 1 МБ чанками |
| P2 | Web UI | Админ-панель для систем и метрик |
| P2 | ONNX Runtime | GPU-ускорение FastJev |
| P3 | OpenTelemetry | Distributed tracing |
