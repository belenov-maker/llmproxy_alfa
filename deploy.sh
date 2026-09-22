#!/bin/bash
###############################################################################
#  PD-Proxy — скрипт автоматического развёртывания
#  Запускайте от root на целевом сервере:
#
#    curl -sSL https://raw.githubusercontent.com/belenov-maker/llmproxy_alfa/main/deploy.sh | bash
#
#  Или скопируйте файл на сервер и выполните:
#
#    chmod +x deploy.sh && ./deploy.sh
#
###############################################################################
set -euo pipefail

# ─── Конфигурация ────────────────────────────────────────────────────────────
APP_DIR="/opt/pd-proxy"
REPO_URL="https://github.com/belenov-maker/llmproxy_alfa.git"
BRANCH="main"
WORKERS=4                    # Кол-во gunicorn-воркеров (рекомендация: кол-во CPU)
PORT=8080                    # Порт сервиса
JEV_ENABLED="true"           # true = regex + FastJev (anti-FP), false = только regex
LOG_LEVEL="info"

# ─── Цвета ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[INFO]${NC}  $1"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $1"; exit 1; }

# ─── Проверка прав ───────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    fail "Скрипт нужно запускать от root: sudo ./deploy.sh"
fi

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║          PD-Proxy — Автоматическое развёртывание        ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ─── Шаг 1: Определение ОС и установка зависимостей ─────────────────────────
info "Шаг 1/8: Установка системных зависимостей..."

if command -v apt-get &>/dev/null; then
    # Debian / Ubuntu
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq python3 python3-venv python3-pip \
        gcc g++ cmake curl git >/dev/null 2>&1
    ok "Системные пакеты установлены (apt)"
elif command -v dnf &>/dev/null; then
    # Fedora / RHEL 8+
    dnf install -y -q python3 python3-devel gcc gcc-c++ cmake curl git >/dev/null 2>&1
    ok "Системные пакеты установлены (dnf)"
elif command -v yum &>/dev/null; then
    # CentOS 7
    yum install -y -q python3 python3-devel gcc gcc-c++ cmake3 curl git >/dev/null 2>&1
    ok "Системные пакеты установлены (yum)"
else
    fail "Неподдерживаемая ОС. Нужен apt-get, dnf или yum."
fi

# Проверка версии Python
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 11 ]]; then
    fail "Python 3.11+ требуется (найден: $PYTHON_VERSION)"
fi
ok "Python $PYTHON_VERSION"

# ─── Шаг 2: Клонирование репозитория ────────────────────────────────────────
info "Шаг 2/8: Клонирование репозитория..."

if [[ -d "$APP_DIR/.git" ]]; then
    warn "Каталог $APP_DIR уже существует — обновляю (git pull)"
    cd "$APP_DIR"
    git fetch origin
    git reset --hard "origin/$BRANCH"
else
    mkdir -p "$(dirname $APP_DIR)"
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi
ok "Репозиторий: $APP_DIR"

# ─── Шаг 3: Виртуальное окружение ───────────────────────────────────────────
info "Шаг 3/8: Создание виртуального окружения..."

if [[ ! -d "$APP_DIR/.venv" ]]; then
    python3 -m venv "$APP_DIR/.venv"
fi
source "$APP_DIR/.venv/bin/activate"
pip install --upgrade pip -q
ok "venv: $APP_DIR/.venv"

# ─── Шаг 4: Установка зависимостей Python ───────────────────────────────────
info "Шаг 4/8: Установка Python-зависимостей (3–7 минут, компиляция llama-cpp)..."

pip install -r "$APP_DIR/requirements.txt" -q 2>&1 | tail -3
ok "Все зависимости установлены"

# ─── Шаг 5: Предзагрузка модели FastJev ─────────────────────────────────────
if [[ "$JEV_ENABLED" == "true" ]]; then
    info "Шаг 5/8: Загрузка модели FastJev (~639 МБ)..."
    
    MODEL_DIR="$APP_DIR/models"
    mkdir -p "$MODEL_DIR"
    export HF_HOME="$MODEL_DIR"
    
    python3 -c "
from huggingface_hub import snapshot_download
import os
cache = os.path.join(os.environ['HF_HOME'], 'hub')
existing = os.path.exists(cache) and any('qwen' in d.lower() for d in os.listdir(cache)) if os.path.exists(cache) else False
if not existing:
    print('Скачиваю Qwen3-0.6B...')
    snapshot_download('Qwen/Qwen3-0.6B')
    print('Модель загружена')
else:
    print('Модель уже в кэше')
" 2>&1
    ok "Модель FastJev готова"
else
    info "Шаг 5/8: FastJev отключён, модель не требуется"
    ok "Пропущено"
fi

# ─── Шаг 6: Создание системного пользователя ────────────────────────────────
info "Шаг 6/8: Настройка системного пользователя..."

if ! id pdproxy &>/dev/null; then
    useradd -r -s /bin/false -d "$APP_DIR" pdproxy
    ok "Пользователь pdproxy создан"
else
    ok "Пользователь pdproxy уже существует"
fi
chown -R pdproxy:pdproxy "$APP_DIR"

# ─── Шаг 7: Создание systemd-unit ───────────────────────────────────────────
info "Шаг 7/8: Настройка systemd-сервиса..."

cat > /etc/systemd/system/pd-proxy.service << UNIT
[Unit]
Description=PD-Proxy — модуль защиты персональных данных
After=network.target
Wants=network-online.target

[Service]
Type=exec
User=pdproxy
Group=pdproxy
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/gunicorn app.main:app -c gunicorn.conf.py
ExecReload=/bin/kill -HUP \$MAINPID
Restart=on-failure
RestartSec=5
TimeoutStartSec=120
TimeoutStopSec=30

# Переменные окружения
Environment=PD_PROXY_WORKERS=$WORKERS
Environment=PD_PROXY_PORT=$PORT
Environment=PD_PROXY_LOG_LEVEL=$LOG_LEVEL
Environment=PD_PROXY_JEV_ENABLED=$JEV_ENABLED
Environment=PD_PROXY_JEV_MODEL=Qwen/Qwen3-0.6B
Environment=PD_PROXY_AUTH_ENABLED=false
Environment=PD_PROXY_STORAGE_TTL_SECONDS=3600
Environment=PD_PROXY_STORAGE_MAX_SIZE=100000
Environment=HF_HOME=$APP_DIR/models

# Безопасность
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$APP_DIR/models $APP_DIR/config
PrivateTmp=true

# Лимиты
LimitNOFILE=65535
LimitNPROC=4096

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable pd-proxy --quiet
ok "systemd-сервис создан и включён в автозапуск"

# ─── Шаг 8: Запуск и проверка ───────────────────────────────────────────────
info "Шаг 8/8: Запуск PD-Proxy..."

systemctl restart pd-proxy

# Ждём готовности (до 60 секунд)
echo -n "  Ожидание старта "
for i in $(seq 1 30); do
    if curl -sf "http://localhost:$PORT/health" >/dev/null 2>&1; then
        echo ""
        ok "PD-Proxy запущен и отвечает!"
        break
    fi
    echo -n "."
    sleep 2
done

# Финальная проверка
if curl -sf "http://localhost:$PORT/health" >/dev/null 2>&1; then
    HEALTH=$(curl -s "http://localhost:$PORT/health")
    echo ""
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║                  ✅ Развёртывание завершено              ║"
    echo "╠══════════════════════════════════════════════════════════╣"
    echo "║                                                          ║"
    echo "║  API:       http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):$PORT/process    ║"
    echo "║  UI:        http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):$PORT/ui/        ║"
    echo "║  Метрики:   http://localhost:$PORT/metrics               ║"
    echo "║  Health:    $HEALTH"
    echo "║                                                          ║"
    echo "║  Логи:      journalctl -u pd-proxy -f                   ║"
    echo "║  Статус:    systemctl status pd-proxy                    ║"
    echo "║  Рестарт:   systemctl restart pd-proxy                   ║"
    echo "║                                                          ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo ""

    # Smoke-тест маскирования
    info "Smoke-тест маскирования..."
    RESULT=$(curl -s -X POST "http://localhost:$PORT/process" \
        -H "Content-Type: application/json" \
        -d '{"payload":"Иванов Иван Иванович, паспорт 4510 123456, тел +7(999)123-45-67","payload_id":"deploy-test","system_id":"default"}')
    
    ACTION=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('action',''))" 2>/dev/null || echo "")
    PD_FOUND=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('stats',{}).get('pd_found',0))" 2>/dev/null || echo "0")
    
    if [[ "$ACTION" == "masked" && "$PD_FOUND" -gt 0 ]]; then
        ok "Smoke-тест пройден: action=$ACTION, pd_found=$PD_FOUND"
    else
        warn "Smoke-тест: неожиданный результат — $RESULT"
    fi
else
    echo ""
    fail "PD-Proxy не запустился. Проверьте логи: journalctl -u pd-proxy -n 50"
fi
