# Руководство по развёртыванию PD-Proxy

> Пошаговая инструкция по установке и запуску сервиса PD-Proxy на внешнем сервере.

## Оглавление

1. [Требования к серверу](#1-требования-к-серверу)
2. [Подготовка сервера](#2-подготовка-сервера)
3. [Развёртывание через Docker (рекомендуется)](#3-развёртывание-через-docker-рекомендуется)
4. [Развёртывание без Docker](#4-развёртывание-без-docker)
5. [Конфигурация](#5-конфигурация)
6. [Проверка работоспособности](#6-проверка-работоспособности)
7. [Настройка reverse proxy (nginx)](#7-настройка-reverse-proxy-nginx)
8. [Мониторинг (Prometheus + Grafana)](#8-мониторинг-prometheus--grafana)
9. [Автозапуск (systemd)](#9-автозапуск-systemd)
10. [Обновление](#10-обновление)
11. [Устранение неполадок](#11-устранение-неполадок)

---

## 1. Требования к серверу

### Аппаратные требования

| Параметр | Режим `fast` (только regex) | Режим `full` (regex + FastJev) | Продакшн (high-load) |
|---|---|---|---|
| **CPU** | 2 vCPU | 4 vCPU | 8 vCPU |
| **RAM** | 2 ГБ | 4 ГБ | 8 ГБ |
| **Диск** | 10 ГБ SSD | 15 ГБ SSD | 30 ГБ SSD |
| **Ожидаемый RPS** | 3 000–5 000 | 1 000–2 000 | 5 000+ |

> **GPU не требуется.** FastJev работает на CPU через llama.cpp.

### Потребление RAM (детализация)

| Компонент | RAM |
|---|---|
| Python + FastAPI + 1 воркер | ~150 МБ |
| Модель Qwen3-0.6B (GGUF Q8_0) | ~700 МБ на каждый воркер |
| In-memory storage (100K записей) | ~200 МБ |
| **Итого: 1 воркер + FastJev** | **~1.5 ГБ** |
| **Итого: 4 воркера + FastJev** | **~3.5 ГБ** |

### Сетевые требования

| Порт | Направление | Назначение |
|---|---|---|
| `8080/tcp` | Входящий | API PD-Proxy |
| `443/tcp` | Исходящий | LLM API (только для `/proxy`) |
| `443/tcp` | Исходящий | Hugging Face Hub (только первая загрузка модели) |

> В режиме `fast` или `full` без `/proxy` исходящий интернет **не нужен** (после скачивания модели).

### Программные требования

**Вариант Docker (рекомендуется):**
- ОС: Ubuntu 22.04+ / Debian 12+ / CentOS 8+ / любой Linux с Docker
- Docker Engine 20.10+
- Docker Compose v2.0+

**Вариант без Docker:**
- ОС: Ubuntu 22.04+ / Debian 12+ (рекомендуется), macOS 13+
- Python 3.11+ (рекомендуется 3.12)
- gcc / g++ (для компиляции llama-cpp-python)
- CMake 3.16+
- curl (для healthcheck)

---

## 2. Подготовка сервера

### 2.1. Обновление системы

```bash
sudo apt update && sudo apt upgrade -y
```

### 2.2. Установка Docker (если выбран Docker-вариант)

```bash
# Установка Docker
curl -fsSL https://get.docker.com | sudo sh

# Добавление текущего пользователя в группу docker
sudo usermod -aG docker $USER
newgrp docker

# Проверка
docker --version
docker compose version
```

### 2.3. Установка build-зависимостей (если без Docker)

```bash
sudo apt install -y python3.12 python3.12-venv python3-pip \
    gcc g++ cmake curl git
```

### 2.4. Клонирование репозитория

```bash
cd /opt
sudo mkdir -p pd-proxy && sudo chown $USER:$USER pd-proxy
git clone https://github.com/belenov-maker/llmproxy_alfa.git pd-proxy
cd pd-proxy
```

---

## 3. Развёртывание через Docker (рекомендуется)

### 3.1. Конфигурация окружения

Создайте файл `.env` в корне проекта:

```bash
cat > .env << 'EOF'
# === Основные настройки ===
PD_PROXY_WORKERS=4
PD_PROXY_LOG_LEVEL=info
PD_PROXY_PORT=8080

# === Режим работы ===
# true = regex + FastJev (anti-FP), false = только regex
PD_PROXY_JEV_ENABLED=true
PD_PROXY_JEV_MODEL=Qwen/Qwen3-0.6B

# === Аутентификация ===
# true = требовать API-key в заголовке X-API-Key
PD_PROXY_AUTH_ENABLED=false

# === Хранилище маппингов ===
PD_PROXY_STORAGE_TTL_SECONDS=3600
PD_PROXY_STORAGE_MAX_SIZE=100000

# === LLM Proxy (необязательно, только для /proxy) ===
# PD_PROXY_LLM_BASE_URL=https://api.deepseek.com/v1
# PD_PROXY_LLM_API_KEY=sk-xxxxxxxxxxxx
# PD_PROXY_LLM_MODEL=deepseek-ai/DeepSeek-V4-Flash-0731
EOF
```

### 3.2. Сборка и запуск

```bash
# Сборка образа (3–5 минут, компиляция llama-cpp-python)
docker compose build

# Запуск в фоновом режиме
docker compose up -d

# Просмотр логов
docker compose logs -f pd-proxy
```

### 3.3. Проверка запуска

```bash
# Подождите 20–30 секунд (загрузка модели при первом запуске)
docker compose ps

# Healthcheck
curl -s http://localhost:8080/health | python3 -m json.tool
```

Ожидаемый ответ:
```json
{
    "status": "ok",
    "version": "0.1.0"
}
```

### 3.4. Управление контейнером

```bash
# Остановка
docker compose down

# Перезапуск
docker compose restart

# Просмотр ресурсов
docker stats pd-proxy-pd-proxy-1

# Полная пересборка (после обновления кода)
docker compose down
docker compose build --no-cache
docker compose up -d
```

> **Важно:** Volume `pd-proxy-models` хранит скачанную модель FastJev (~639 МБ). При `docker compose down` volume сохраняется. Для полной очистки: `docker compose down -v`.

---

## 4. Развёртывание без Docker

### 4.1. Создание виртуального окружения

```bash
cd /opt/pd-proxy
python3.12 -m venv .venv
source .venv/bin/activate
```

### 4.2. Установка зависимостей

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

> **Время установки:** 3–7 минут. Пакет `llama-cpp-python` компилируется из исходников (требуется gcc/g++/cmake).

Если компиляция `llama-cpp-python` падает с ошибкой:
```bash
# Установка недостающих зависимостей
sudo apt install -y build-essential cmake

# Повторная установка
pip install llama-cpp-python --no-cache-dir
pip install -r requirements.txt
```

### 4.3. Настройка переменных окружения

```bash
# Создайте файл с переменными
cat > /opt/pd-proxy/.env.sh << 'EOF'
export PD_PROXY_WORKERS=4
export PD_PROXY_LOG_LEVEL=info
export PD_PROXY_PORT=8080
export PD_PROXY_JEV_ENABLED=true
export PD_PROXY_JEV_MODEL=Qwen/Qwen3-0.6B
export PD_PROXY_AUTH_ENABLED=false
export PD_PROXY_STORAGE_TTL_SECONDS=3600
export PD_PROXY_STORAGE_MAX_SIZE=100000
export HF_HOME=/opt/pd-proxy/models
EOF

# Загрузите переменные
source /opt/pd-proxy/.env.sh
```

### 4.4. Предзагрузка модели FastJev

При первом запуске модель скачивается с Hugging Face Hub (~639 МБ). Можно скачать заранее:

```bash
source .venv/bin/activate
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('Qwen/Qwen3-0.6B', local_dir='models/Qwen3-0.6B')
print('Модель загружена успешно')
"
```

> **Офлайн-режим:** если сервер без интернета, скачайте модель на машине с доступом и скопируйте каталог `models/` на сервер через `scp`.

### 4.5. Запуск

```bash
source .venv/bin/activate
source .env.sh

# Режим разработки (1 воркер, auto-reload)
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

# Продакшн (multi-worker через gunicorn)
gunicorn app.main:app -c gunicorn.conf.py
```

### 4.6. Запуск тестов

```bash
source .venv/bin/activate
pytest tests/ -v
```

Ожидаемый результат: `190 passed`.

---

## 5. Конфигурация

### 5.1. Переменные окружения

Все настройки задаются через переменные с префиксом `PD_PROXY_`:

| Переменная | Тип | По умолчанию | Описание |
|---|---|---|---|
| `PD_PROXY_PORT` | int | `8080` | Порт сервиса |
| `PD_PROXY_WORKERS` | int | `1` | Количество воркеров gunicorn |
| `PD_PROXY_LOG_LEVEL` | str | `info` | Уровень логов (`debug`, `info`, `warning`, `error`) |
| `PD_PROXY_AUTH_ENABLED` | bool | `false` | Включить аутентификацию по API-key |
| `PD_PROXY_JEV_ENABLED` | bool | `true` | Включить FastJev (anti-FP через LLM) |
| `PD_PROXY_JEV_MODEL` | str | `Qwen/Qwen3-0.6B` | Модель FastJev |
| `PD_PROXY_JEV_CONFIDENCE_THRESHOLD` | float | `0.6` | Порог уверенности FastJev (0.0–1.0) |
| `PD_PROXY_JEV_MAX_INPUT_TOKENS` | int | `4096` | Макс. токенов на вход FastJev |
| `PD_PROXY_STORAGE_TTL_SECONDS` | int | `3600` | TTL маппингов маскирования (секунды) |
| `PD_PROXY_STORAGE_MAX_SIZE` | int | `100000` | Макс. количество маппингов в памяти |
| `PD_PROXY_LLM_BASE_URL` | str | `""` | URL внешнего LLM API (для `/proxy`) |
| `PD_PROXY_LLM_API_KEY` | str | `""` | API-ключ LLM |
| `PD_PROXY_LLM_MODEL` | str | `deepseek-ai/DeepSeek-V4-Flash-0731` | Модель LLM |
| `PD_PROXY_SYSTEMS_CONFIG_PATH` | str | `config/systems.yaml` | Путь к конфигу систем |

### 5.2. Конфигурация систем (`config/systems.yaml`)

Файл определяет профили обработки для разных систем-потребителей:

```yaml
auth_enabled: false

systems:
  default:
    description: "Настройки по умолчанию"
    api_key: "your-secure-api-key-here"    # Используется при auth_enabled: true
    mode: full                              # full | fast
    masking_style: placeholder              # placeholder | partial
    pd_categories:
      - fio
      - passport
      - snils
      - inn
      - phone
      - email
      - card_number
      - address
      - birth_date
      # ... полный список — 21 категория

  # Пример: отдельный профиль для системы с быстрым режимом
  crm-system:
    description: "CRM — только regex, минимум категорий"
    api_key: "crm-secret-key"
    mode: fast
    masking_style: placeholder
    pd_categories: [fio, phone, email, inn]
```

**Режимы работы:**
- `fast` — только regex-детекция, <1 мс на запрос, до 9 000 RPS
- `full` — regex + FastJev (антиложноположительные), ~5–15 мс на запрос, до 2 000 RPS

**Стили маскирования:**
- `placeholder` — замена на `[FIO_1]`, `[PHONE_1]`, `[PASSPORT_1]` и т.д.
- `partial` — частичное маскирование: `Ива*** И*** И***`, `+7(***) ***-45-67`

> Файл перечитывается автоматически при изменении (hot-reload по mtime), перезапуск сервиса не требуется.

### 5.3. Рекомендация по количеству воркеров

| Режим | Формула | Пример (4 vCPU) |
|---|---|---|
| `fast` | `CPU × 2 + 1` | 9 воркеров |
| `full` | `CPU` | 4 воркера |

В режиме `full` каждый воркер загружает модель (~700 МБ RAM). Не ставьте больше воркеров, чем позволяет RAM.

---

## 6. Проверка работоспособности

### 6.1. Healthcheck

```bash
curl -s http://localhost:8080/health
# {"status":"ok","version":"0.1.0"}
```

### 6.2. Тест маскирования

```bash
curl -s -X POST http://localhost:8080/process \
  -H "Content-Type: application/json" \
  -d '{
    "payload": "Иванов Иван Иванович, паспорт 4510 123456, телефон +7(999)123-45-67, email ivan@mail.ru",
    "payload_id": "test-001",
    "system_id": "default"
  }' | python3 -m json.tool
```

Ожидаемый ответ:
```json
{
    "result": "[FIO_1], паспорт [PASSPORT_1], телефон [PHONE_1], email [EMAIL_1]",
    "payload_id": "test-001",
    "action": "masked",
    "stats": {
        "pd_found": 4,
        "categories": ["fio", "passport", "phone", "email"],
        "regex_ms": 0.35,
        "jev_ms": 12.5,
        "total_ms": 13.1
    }
}
```

### 6.3. Тест демаскирования (повторный запрос с тем же `payload_id`)

```bash
curl -s -X POST http://localhost:8080/process \
  -H "Content-Type: application/json" \
  -d '{
    "payload": "[FIO_1] позвонил по номеру [PHONE_1]",
    "payload_id": "test-001",
    "system_id": "default"
  }' | python3 -m json.tool
```

Ответ с восстановленными данными:
```json
{
    "result": "Иванов Иван Иванович позвонил по номеру +7(999)123-45-67",
    "payload_id": "test-001",
    "action": "unmasked"
}
```

### 6.4. Метрики Prometheus

```bash
curl -s http://localhost:8080/metrics
```

### 6.5. Веб-консоль

Откройте в браузере: `http://<IP-сервера>:8080/ui/`

---

## 7. Настройка reverse proxy (nginx)

### 7.1. Установка nginx

```bash
sudo apt install -y nginx
```

### 7.2. Конфигурация

```bash
sudo tee /etc/nginx/sites-available/pd-proxy << 'EOF'
upstream pd_proxy {
    server 127.0.0.1:8080;
    keepalive 32;
}

server {
    listen 80;
    server_name pd-proxy.example.com;    # Замените на ваш домен/IP

    # Ограничение размера тела запроса (100K токенов ≈ 400 КБ)
    client_max_body_size 2m;

    # Таймауты
    proxy_connect_timeout 5s;
    proxy_read_timeout 120s;    # LLM proxy может быть медленным
    proxy_send_timeout 30s;

    location / {
        proxy_pass http://pd_proxy;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }

    # Метрики — доступ только из внутренней сети
    location /metrics {
        allow 10.0.0.0/8;
        allow 172.16.0.0/12;
        allow 192.168.0.0/16;
        allow 127.0.0.1;
        deny all;
        proxy_pass http://pd_proxy;
    }

    # Admin — доступ только из внутренней сети
    location /admin/ {
        allow 10.0.0.0/8;
        allow 172.16.0.0/12;
        allow 192.168.0.0/16;
        allow 127.0.0.1;
        deny all;
        proxy_pass http://pd_proxy;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/pd-proxy /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 7.3. HTTPS (Let's Encrypt)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d pd-proxy.example.com
```

---

## 8. Мониторинг (Prometheus + Grafana)

### 8.1. Доступные метрики

PD-Proxy отдаёт метрики в формате Prometheus на `GET /metrics`:

| Метрика | Тип | Описание |
|---|---|---|
| `pd_proxy_requests_total` | counter | Общее количество запросов |
| `pd_proxy_request_latency_seconds` | histogram | Латентность запросов |
| `pd_proxy_pd_detected_total` | counter | Количество найденных ПДн |
| `pd_proxy_jev_filtered_total` | counter | Отфильтровано FastJev (anti-FP) |
| `pd_proxy_storage_size` | gauge | Текущий размер хранилища маппингов |

### 8.2. Конфигурация Prometheus

Добавьте в `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'pd-proxy'
    scrape_interval: 15s
    static_configs:
      - targets: ['pd-proxy-host:8080']
    metrics_path: /metrics
```

### 8.3. Алерты (пример)

```yaml
groups:
  - name: pd-proxy
    rules:
      - alert: PDProxyDown
        expr: up{job="pd-proxy"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "PD-Proxy недоступен"

      - alert: PDProxyHighLatency
        expr: histogram_quantile(0.99, pd_proxy_request_latency_seconds_bucket) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "p99 латентность выше 1 секунды"
```

---

## 9. Автозапуск (systemd)

Для варианта без Docker — создайте systemd-unit:

```bash
sudo tee /etc/systemd/system/pd-proxy.service << 'EOF'
[Unit]
Description=PD-Proxy — модуль защиты персональных данных
After=network.target
Wants=network-online.target

[Service]
Type=exec
User=pdproxy
Group=pdproxy
WorkingDirectory=/opt/pd-proxy
ExecStart=/opt/pd-proxy/.venv/bin/gunicorn app.main:app -c gunicorn.conf.py
ExecReload=/bin/kill -HUP $MAINPID
Restart=on-failure
RestartSec=5
TimeoutStartSec=60
TimeoutStopSec=30

# Переменные окружения
EnvironmentFile=/opt/pd-proxy/.env.sh
Environment=HF_HOME=/opt/pd-proxy/models
Environment=PD_PROXY_WORKERS=4
Environment=PD_PROXY_JEV_ENABLED=true
Environment=PD_PROXY_LOG_LEVEL=info

# Безопасность
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/opt/pd-proxy/models /opt/pd-proxy/config
PrivateTmp=true

# Лимиты
LimitNOFILE=65535
LimitNPROC=4096

[Install]
WantedBy=multi-user.target
EOF
```

Создайте пользователя и настройте права:

```bash
# Создание системного пользователя
sudo useradd -r -s /bin/false -d /opt/pd-proxy pdproxy
sudo chown -R pdproxy:pdproxy /opt/pd-proxy

# Активация и запуск
sudo systemctl daemon-reload
sudo systemctl enable pd-proxy
sudo systemctl start pd-proxy

# Проверка статуса
sudo systemctl status pd-proxy

# Просмотр логов
sudo journalctl -u pd-proxy -f
```

---

## 10. Обновление

### Docker

```bash
cd /opt/pd-proxy
git pull origin main
docker compose down
docker compose build
docker compose up -d
```

### Без Docker

```bash
cd /opt/pd-proxy
git pull origin main
source .venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart pd-proxy
```

### Обновление с нулевым простоем (graceful reload)

```bash
# Gunicorn поддерживает hot-reload воркеров
sudo systemctl reload pd-proxy    # отправляет HUP
```

---

## 11. Устранение неполадок

### Сервис не запускается

```bash
# Проверка логов
docker compose logs pd-proxy          # Docker
sudo journalctl -u pd-proxy -n 50     # systemd

# Частые причины:
# 1. Порт 8080 занят
sudo lsof -i :8080

# 2. Нет прав на каталог models/
ls -la /opt/pd-proxy/models/

# 3. Не хватает RAM для модели
free -h
```

### Ошибка компиляции llama-cpp-python

```bash
# Убедитесь, что установлены build-зависимости
sudo apt install -y gcc g++ cmake build-essential

# Попробуйте установить с verbose
pip install llama-cpp-python -v --no-cache-dir
```

### Модель не скачивается (нет интернета)

```bash
# На машине с интернетом:
pip install huggingface_hub
python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('Qwen/Qwen3-0.6B', local_dir='./Qwen3-0.6B')
"

# Скопируйте на сервер:
scp -r ./Qwen3-0.6B user@server:/opt/pd-proxy/models/

# Укажите локальный путь:
export PD_PROXY_JEV_MODEL=/opt/pd-proxy/models/Qwen3-0.6B
```

### Высокая латентность в режиме `full`

```bash
# 1. Проверьте количество воркеров (не больше, чем позволяет RAM)
curl -s http://localhost:8080/metrics | grep storage_size

# 2. Переключитесь на fast для высоконагруженных систем
# В config/systems.yaml:
#   high-load-system:
#     mode: fast

# 3. Уменьшите порог FastJev (больше FP, но быстрее)
export PD_PROXY_JEV_CONFIDENCE_THRESHOLD=0.5
```

### Rate limiting (429 Too Many Requests)

По умолчанию лимит — 5 000 rps с burst 200. Если получаете 429:

```bash
# Проверьте текущий RPS
curl -s http://localhost:8080/metrics | grep requests_total
```

Лимит настраивается в коде (`app/main.py`, middleware `RateLimitMiddleware`).

### Хранилище маппингов переполнено

```bash
# Проверьте размер
curl -s http://localhost:8080/admin/stats

# Увеличьте лимит или уменьшите TTL
export PD_PROXY_STORAGE_MAX_SIZE=500000
export PD_PROXY_STORAGE_TTL_SECONDS=1800
```

---

## Быстрый старт (TL;DR)

```bash
# 1. Клонируем
git clone https://github.com/belenov-maker/llmproxy_alfa.git pd-proxy
cd pd-proxy

# 2. Запускаем
docker compose up -d

# 3. Ждём 30 секунд (загрузка модели), проверяем
curl http://localhost:8080/health

# 4. Тестируем
curl -X POST http://localhost:8080/process \
  -H "Content-Type: application/json" \
  -d '{"payload":"Иванов Иван, паспорт 4510 123456","payload_id":"t1","system_id":"default"}'

# 5. Открываем веб-консоль
open http://localhost:8080/ui/
```
