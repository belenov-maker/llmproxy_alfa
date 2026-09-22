#!/bin/bash
###############################################################################
#  PD-Proxy — скрипт автоматического развёртывания (Docker)
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
PORT=8080

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
echo "║       PD-Proxy — Автоматическое развёртывание (Docker)  ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ─── Шаг 0: Очистка предыдущей (нативной) установки ─────────────────────────
if systemctl is-active pd-proxy &>/dev/null 2>&1 || systemctl is-enabled pd-proxy &>/dev/null 2>&1; then
    info "Шаг 0: Обнаружена предыдущая нативная установка — откатываю..."
    systemctl stop pd-proxy 2>/dev/null || true
    systemctl disable pd-proxy 2>/dev/null || true
    rm -f /etc/systemd/system/pd-proxy.service
    systemctl daemon-reload
    ok "systemd-сервис pd-proxy остановлен и удалён"

    if [[ -d "$APP_DIR/.venv" ]]; then
        rm -rf "$APP_DIR/.venv"
        ok "Виртуальное окружение .venv удалено"
    fi

    if id pdproxy &>/dev/null; then
        userdel pdproxy 2>/dev/null || true
        ok "Системный пользователь pdproxy удалён"
    fi
else
    info "Шаг 0: Предыдущая нативная установка не обнаружена — пропускаю"
fi

# ─── Шаг 1: Установка Docker ────────────────────────────────────────────────
info "Шаг 1/5: Проверка и установка Docker..."

if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    DOCKER_VER=$(docker --version | awk '{print $3}' | tr -d ',')
    ok "Docker уже установлен ($DOCKER_VER)"
else
    info "Устанавливаю Docker..."
    if command -v apt-get &>/dev/null; then
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq
        apt-get install -y -qq ca-certificates curl gnupg >/dev/null 2>&1
    fi
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker --quiet
    systemctl start docker
    ok "Docker установлен"
fi

# Проверка Docker Compose
if docker compose version &>/dev/null 2>&1; then
    COMPOSE_VER=$(docker compose version --short 2>/dev/null || echo "v2+")
    ok "Docker Compose ($COMPOSE_VER)"
else
    fail "Docker Compose не найден. Установите: apt install docker-compose-plugin"
fi

# ─── Шаг 2: Клонирование репозитория ────────────────────────────────────────
info "Шаг 2/5: Клонирование репозитория..."

if [[ -d "$APP_DIR/.git" ]]; then
    warn "Каталог $APP_DIR уже существует — обновляю (git pull)"
    git config --global --add safe.directory "$APP_DIR"
    cd "$APP_DIR"
    git fetch origin
    git reset --hard "origin/$BRANCH"
else
    if ! command -v git &>/dev/null; then
        apt-get update -qq && apt-get install -y -qq git >/dev/null 2>&1
    fi
    mkdir -p "$(dirname "$APP_DIR")"
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi
ok "Репозиторий: $APP_DIR"

# ─── Шаг 3: Создание .env ───────────────────────────────────────────────────
info "Шаг 3/5: Настройка окружения..."

if [[ ! -f "$APP_DIR/.env" ]]; then
    cat > "$APP_DIR/.env" << 'ENVFILE'
PD_PROXY_WORKERS=4
PD_PROXY_LOG_LEVEL=info
PD_PROXY_AUTH_ENABLED=false
PD_PROXY_JEV_ENABLED=true
PD_PROXY_JEV_MODEL=Qwen/Qwen3-0.6B
PD_PROXY_STORAGE_TTL_SECONDS=3600
PD_PROXY_STORAGE_MAX_SIZE=100000
# PD_PROXY_LLM_BASE_URL=https://api.deepseek.com/v1
# PD_PROXY_LLM_API_KEY=sk-xxxxxxxxxxxx
# PD_PROXY_LLM_MODEL=deepseek-ai/DeepSeek-V4-Flash-0731
ENVFILE
    ok ".env создан (настройки по умолчанию)"
else
    ok ".env уже существует — оставляю без изменений"
fi

# ─── Шаг 4: Сборка и запуск ─────────────────────────────────────────────────
info "Шаг 4/5: Сборка Docker-образа (3–7 минут)..."

cd "$APP_DIR"

# Остановка предыдущей версии (если есть)
docker compose down 2>/dev/null || true

# Сборка
docker compose build --progress=plain 2>&1 | tail -5
ok "Docker-образ собран"

info "Запуск контейнера..."
docker compose up -d
ok "Контейнер запущен"

# ─── Шаг 5: Проверка ────────────────────────────────────────────────────────
info "Шаг 5/5: Проверка работоспособности..."

echo -n "  Ожидание старта (загрузка модели ~30с) "
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
    SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost')

    # Smoke-тест
    RESULT=$(curl -s -X POST "http://localhost:$PORT/process" \
        -H "Content-Type: application/json" \
        -d '{"payload":"Иванов Иван Иванович, паспорт 4510 123456, тел +7(999)123-45-67","payload_id":"deploy-test","system_id":"default"}')
    
    ACTION=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('action',''))" 2>/dev/null || echo "?")
    PD_FOUND=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('stats',{}).get('pd_found',0))" 2>/dev/null || echo "?")

    echo ""
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║               ✅ Развёртывание завершено                 ║"
    echo "╠══════════════════════════════════════════════════════════╣"
    echo "║                                                          ║"
    echo "║  API:        http://$SERVER_IP:$PORT/process"
    echo "║  UI:         http://$SERVER_IP:$PORT/ui/"
    echo "║  Метрики:    http://$SERVER_IP:$PORT/metrics"
    echo "║  Health:     $HEALTH"
    echo "║  Smoke-тест: action=$ACTION, pd_found=$PD_FOUND"
    echo "║                                                          ║"
    echo "║  Логи:       docker compose -f $APP_DIR/docker-compose.yml logs -f"
    echo "║  Статус:     docker compose -f $APP_DIR/docker-compose.yml ps"
    echo "║  Рестарт:    docker compose -f $APP_DIR/docker-compose.yml restart"
    echo "║  Остановка:  docker compose -f $APP_DIR/docker-compose.yml down"
    echo "║                                                          ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo ""
else
    echo ""
    warn "PD-Proxy не ответил за 60 секунд. Проверьте логи:"
    echo "  docker compose -f $APP_DIR/docker-compose.yml logs --tail 50"
    exit 1
fi
