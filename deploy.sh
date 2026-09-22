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
TOTAL_STEPS=5
DEPLOY_START=$(date +%s)
LOG_FILE="/tmp/pd-proxy-deploy-$(date +%Y%m%d-%H%M%S).log"

# ─── Цвета ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

# ─── Утилиты логирования ────────────────────────────────────────────────────
ts()    { date '+%H:%M:%S'; }
info()  { echo -e "${DIM}$(ts)${NC} ${BLUE}[INFO]${NC}  $1"; }
ok()    { echo -e "${DIM}$(ts)${NC} ${GREEN}[ OK ]${NC}  $1"; }
warn()  { echo -e "${DIM}$(ts)${NC} ${YELLOW}[WARN]${NC}  $1"; }
fail()  { echo -e "${DIM}$(ts)${NC} ${RED}[FAIL]${NC}  $1"; exit 1; }
detail(){ echo -e "${DIM}$(ts)        ↳ $1${NC}"; }

elapsed_since() {
    local start=$1
    local now=$(date +%s)
    local diff=$((now - start))
    if (( diff < 60 )); then
        echo "${diff}с"
    else
        echo "$((diff / 60))м $((diff % 60))с"
    fi
}

# ─── Прогресс-бар ───────────────────────────────────────────────────────────
# Использование: progress_bar <текущий_шаг> <всего_шагов> <описание>
progress_bar() {
    local current=$1
    local total=$2
    local desc=$3
    local pct=$((current * 100 / total))
    local filled=$((pct / 5))       # 20 символов = 100%
    local empty=$((20 - filled))
    local bar=""
    for ((i=0; i<filled; i++)); do bar+="█"; done
    for ((i=0; i<empty; i++));  do bar+="░"; done
    local elapsed=$(elapsed_since "$DEPLOY_START")

    echo ""
    echo -e "${BOLD}${CYAN}  [$bar] ${pct}%  │  Шаг ${current}/${total}: ${desc}  │  ⏱ ${elapsed}${NC}"
    echo ""
}

# Спиннер для длительных операций
# Использование: start_spinner "сообщение" ; <команда> ; stop_spinner
SPINNER_PID=""
start_spinner() {
    local msg="$1"
    (
        local chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
        local i=0
        local start=$(date +%s)
        while true; do
            local now=$(date +%s)
            local elapsed=$((now - start))
            local c=${chars:i%10:1}
            printf "\r  ${CYAN}${c}${NC} ${msg} ${DIM}(${elapsed}с)${NC}  "
            sleep 0.2
            i=$((i + 1))
        done
    ) &
    SPINNER_PID=$!
    disown "$SPINNER_PID" 2>/dev/null
}

stop_spinner() {
    if [[ -n "$SPINNER_PID" ]]; then
        kill "$SPINNER_PID" 2>/dev/null || true
        wait "$SPINNER_PID" 2>/dev/null || true
        SPINNER_PID=""
        printf "\r\033[K"  # очистить строку со спиннером
    fi
}

# Финальная очистка при завершении
cleanup() {
    stop_spinner
}
trap cleanup EXIT

# ─── Проверка прав ───────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    fail "Скрипт нужно запускать от root: sudo ./deploy.sh"
fi

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║       PD-Proxy — Автоматическое развёртывание (Docker)  ║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════╣${NC}"
echo -e "${BOLD}║${NC}  Лог:  ${DIM}$LOG_FILE${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# ─── Шаг 0: Очистка предыдущей (нативной) установки ─────────────────────────
info "Шаг 0: Проверка предыдущей нативной установки..."

if systemctl is-active pd-proxy &>/dev/null 2>&1 || systemctl is-enabled pd-proxy &>/dev/null 2>&1; then
    warn "Обнаружена предыдущая нативная установка — откатываю..."
    systemctl stop pd-proxy 2>/dev/null || true
    detail "systemd-сервис остановлен"
    systemctl disable pd-proxy 2>/dev/null || true
    rm -f /etc/systemd/system/pd-proxy.service
    systemctl daemon-reload
    ok "systemd-сервис pd-proxy удалён"

    if [[ -d "$APP_DIR/.venv" ]]; then
        rm -rf "$APP_DIR/.venv"
        detail "Виртуальное окружение .venv удалено"
    fi

    if id pdproxy &>/dev/null; then
        userdel pdproxy 2>/dev/null || true
        detail "Системный пользователь pdproxy удалён"
    fi
    ok "Нативная установка полностью очищена"
else
    ok "Предыдущая нативная установка не обнаружена — пропускаю"
fi

###############################################################################
#  ШАГ 1: Docker
###############################################################################
STEP_START=$(date +%s)
progress_bar 1 $TOTAL_STEPS "Проверка Docker"

if command -v docker &>/dev/null && docker info &>/dev/null 2>&1; then
    DOCKER_VER=$(docker --version | awk '{print $3}' | tr -d ',')
    ok "Docker уже установлен (v${DOCKER_VER})"
else
    info "Docker не найден — устанавливаю..."
    start_spinner "Установка Docker"
    if command -v apt-get &>/dev/null; then
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq >> "$LOG_FILE" 2>&1
        apt-get install -y -qq ca-certificates curl gnupg >> "$LOG_FILE" 2>&1
    fi
    curl -fsSL https://get.docker.com | sh >> "$LOG_FILE" 2>&1
    systemctl enable docker --quiet >> "$LOG_FILE" 2>&1
    systemctl start docker
    stop_spinner
    DOCKER_VER=$(docker --version | awk '{print $3}' | tr -d ',')
    ok "Docker установлен (v${DOCKER_VER})"
fi

# Проверка Docker Compose
if docker compose version &>/dev/null 2>&1; then
    COMPOSE_VER=$(docker compose version --short 2>/dev/null || echo "v2+")
    ok "Docker Compose (v${COMPOSE_VER})"
else
    fail "Docker Compose не найден. Установите: apt install docker-compose-plugin"
fi

detail "Шаг 1 завершён за $(elapsed_since $STEP_START)"

###############################################################################
#  ШАГ 2: Клонирование репозитория
###############################################################################
STEP_START=$(date +%s)
progress_bar 2 $TOTAL_STEPS "Клонирование репозитория"

if [[ -d "$APP_DIR/.git" ]]; then
    warn "Каталог $APP_DIR уже существует — обновляю (git pull)"
    git config --global --add safe.directory "$APP_DIR"
    cd "$APP_DIR"
    start_spinner "git fetch + reset"
    git fetch origin >> "$LOG_FILE" 2>&1
    git reset --hard "origin/$BRANCH" >> "$LOG_FILE" 2>&1
    stop_spinner
    COMMIT=$(git rev-parse --short HEAD)
    ok "Репозиторий обновлён (commit: ${COMMIT})"
else
    if ! command -v git &>/dev/null; then
        info "Устанавливаю git..."
        apt-get update -qq >> "$LOG_FILE" 2>&1
        apt-get install -y -qq git >> "$LOG_FILE" 2>&1
    fi
    mkdir -p "$(dirname "$APP_DIR")"
    start_spinner "git clone"
    git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$APP_DIR" >> "$LOG_FILE" 2>&1
    stop_spinner
    cd "$APP_DIR"
    COMMIT=$(git rev-parse --short HEAD)
    ok "Репозиторий склонирован (commit: ${COMMIT})"
fi

detail "Путь: $APP_DIR"
detail "Ветка: $BRANCH"
detail "Шаг 2 завершён за $(elapsed_since $STEP_START)"

###############################################################################
#  ШАГ 3: Настройка .env
###############################################################################
STEP_START=$(date +%s)
progress_bar 3 $TOTAL_STEPS "Настройка окружения"

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
    detail "Воркеры: 4  │  Jev: ON  │  Auth: OFF"
else
    ok ".env уже существует — оставляю без изменений"
    # Показываем ключевые настройки
    JEV=$(grep -oP 'PD_PROXY_JEV_ENABLED=\K.*' "$APP_DIR/.env" 2>/dev/null || echo "?")
    WORKERS=$(grep -oP 'PD_PROXY_WORKERS=\K.*' "$APP_DIR/.env" 2>/dev/null || echo "?")
    detail "Воркеры: ${WORKERS}  │  Jev: ${JEV}"
fi

detail "Шаг 3 завершён за $(elapsed_since $STEP_START)"

###############################################################################
#  ШАГ 4: Сборка и запуск Docker
###############################################################################
STEP_START=$(date +%s)
progress_bar 4 $TOTAL_STEPS "Сборка Docker-образа"

cd "$APP_DIR"

# Остановка предыдущей версии (если есть)
if docker compose ps --quiet 2>/dev/null | grep -q .; then
    info "Останавливаю предыдущую версию..."
    docker compose down >> "$LOG_FILE" 2>&1
    detail "Предыдущий контейнер остановлен"
fi

# Сборка с подробным логированием
info "Сборка Docker-образа (это может занять 5–15 минут)..."
info "  ├─ Этап 1: Установка системных зависимостей"
info "  ├─ Этап 2: Установка Python-пакетов (pip install)"
info "  ├─ Этап 3: Компиляция llama-cpp-python из C++ (≈5–10 мин)"
info "  ├─ Этап 4: Загрузка модели Qwen3-0.6B (≈640 МБ)"
info "  └─ Этап 5: Копирование приложения"
echo ""

BUILD_LOG="$LOG_FILE"

# Показываем прогресс Docker build в реальном времени
# Фильтруем полезные строки: Step, RUN, COPY, Successfully
docker compose build --progress=plain 2>&1 | while IFS= read -r line; do
    echo "$line" >> "$BUILD_LOG"

    # Показываем ключевые этапы сборки
    if echo "$line" | grep -qE '^\#[0-9]+ \[.* [0-9]+/[0-9]+\]'; then
        # Docker BuildKit step: "#7 [stage-0 3/8] RUN pip install..."
        STEP_NUM=$(echo "$line" | grep -oP '\d+/\d+' | head -1)
        STEP_DESC=$(echo "$line" | sed 's/^#[0-9]* \[.* [0-9]*\/[0-9]*\] //')
        echo -e "  ${DIM}$(ts)${NC}  ${CYAN}[BUILD ${STEP_NUM}]${NC}  ${STEP_DESC}"
    elif echo "$line" | grep -qi 'downloading.*model\|fetching.*model\|downloading.*gguf'; then
        echo -e "  ${DIM}$(ts)${NC}  ${CYAN}[MODEL]${NC}    Загрузка модели..."
    elif echo "$line" | grep -qi 'compil\|cmake\|building wheel\|building extension'; then
        echo -e "  ${DIM}$(ts)${NC}  ${CYAN}[C++]${NC}      Компиляция llama.cpp..."
    elif echo "$line" | grep -qi 'Successfully built\|exporting to image'; then
        echo -e "  ${DIM}$(ts)${NC}  ${GREEN}[BUILD]${NC}    $line"
    elif echo "$line" | grep -qi 'error\|Error\|ERROR'; then
        echo -e "  ${DIM}$(ts)${NC}  ${RED}[ERROR]${NC}    $line"
    elif echo "$line" | grep -qi 'warning\|Warning'; then
        echo -e "  ${DIM}$(ts)${NC}  ${YELLOW}[WARN]${NC}     $line"
    fi
done

BUILD_EXIT=${PIPESTATUS[0]}
if [[ $BUILD_EXIT -ne 0 ]]; then
    echo ""
    fail "Сборка Docker-образа завершилась с ошибкой (код $BUILD_EXIT). Смотрите лог: $LOG_FILE"
fi

BUILD_TIME=$(elapsed_since $STEP_START)
ok "Docker-образ собран за ${BUILD_TIME}"

# Запуск
info "Запуск контейнера..."
docker compose up -d >> "$LOG_FILE" 2>&1
CONTAINER_ID=$(docker compose ps --quiet 2>/dev/null | head -1)
ok "Контейнер запущен (${CONTAINER_ID:0:12})"

detail "Шаг 4 завершён за $(elapsed_since $STEP_START)"

###############################################################################
#  ШАГ 5: Проверка работоспособности
###############################################################################
STEP_START=$(date +%s)
progress_bar 5 $TOTAL_STEPS "Проверка работоспособности"

info "Ожидание старта приложения (загрузка модели ~30с)..."

# Healthcheck с прогрессом
MAX_WAIT=60
HEALTHY=false
for i in $(seq 1 $MAX_WAIT); do
    if curl -sf "http://localhost:$PORT/health" >/dev/null 2>&1; then
        HEALTHY=true
        break
    fi
    # Прогресс-бар ожидания
    pct=$((i * 100 / MAX_WAIT))
    filled=$((pct / 5))
    empty=$((20 - filled))
    bar=""
    for ((j=0; j<filled; j++)); do bar+="█"; done
    for ((j=0; j<empty; j++));  do bar+="░"; done
    printf "\r  ${DIM}Healthcheck: [${bar}] ${pct}%%  (${i}/${MAX_WAIT}с)${NC}  "
    sleep 1
done
printf "\r\033[K"  # очистить строку

if [[ "$HEALTHY" == "true" ]]; then
    ok "Приложение отвечает на /health"
else
    warn "PD-Proxy не ответил за ${MAX_WAIT}с"
    info "Последние логи контейнера:"
    docker compose logs --tail 20
    echo ""
    fail "Healthcheck failed. Полный лог: $LOG_FILE"
fi

# Smoke-тест
info "Smoke-тест: маскирование персональных данных..."
RESULT=$(curl -s -X POST "http://localhost:$PORT/process" \
    -H "Content-Type: application/json" \
    -d '{"payload":"Иванов Иван Иванович, паспорт 4510 123456, тел +7(999)123-45-67","payload_id":"deploy-test","system_id":"default"}')

ACTION=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('action','?'))" 2>/dev/null || echo "?")
PD_FOUND=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('stats',{}).get('pd_found',0))" 2>/dev/null || echo "?")
TOTAL_MS=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('stats',{}).get('total_ms','?'))" 2>/dev/null || echo "?")
CATEGORIES=$(echo "$RESULT" | python3 -c "import sys,json; cats=json.load(sys.stdin).get('stats',{}).get('categories',[]); print(', '.join(cats))" 2>/dev/null || echo "?")

if [[ "$ACTION" == "masked" ]]; then
    ok "Smoke-тест пройден ✓"
    detail "Найдено ПДн: ${PD_FOUND}"
    detail "Категории: ${CATEGORIES}"
    detail "Время ответа: ${TOTAL_MS} мс"
else
    warn "Smoke-тест: неожиданный action='${ACTION}'"
fi

detail "Шаг 5 завершён за $(elapsed_since $STEP_START)"

###############################################################################
#  Итог
###############################################################################
TOTAL_TIME=$(elapsed_since $DEPLOY_START)
SERVER_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost')
IMAGE_SIZE=$(docker images --filter "reference=*pd-proxy*" --format "{{.Size}}" 2>/dev/null | head -1 || echo "?")

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║             ${GREEN}✅ Развёртывание завершено успешно${NC}${BOLD}              ║${NC}"
echo -e "${BOLD}╠══════════════════════════════════════════════════════════════╣${NC}"
echo -e "${BOLD}║${NC}                                                              ${BOLD}║${NC}"
echo -e "${BOLD}║${NC}  ${CYAN}API:${NC}        http://${SERVER_IP}:${PORT}/process                 "
echo -e "${BOLD}║${NC}  ${CYAN}Proxy:${NC}      http://${SERVER_IP}:${PORT}/proxy                   "
echo -e "${BOLD}║${NC}  ${CYAN}UI:${NC}         http://${SERVER_IP}:${PORT}/ui/                     "
echo -e "${BOLD}║${NC}  ${CYAN}Метрики:${NC}    http://${SERVER_IP}:${PORT}/metrics                 "
echo -e "${BOLD}║${NC}  ${CYAN}Health:${NC}     http://${SERVER_IP}:${PORT}/health                  "
echo -e "${BOLD}║${NC}                                                              "
echo -e "${BOLD}║${NC}  ${DIM}Время сборки:  ${TOTAL_TIME}${NC}                                    "
echo -e "${BOLD}║${NC}  ${DIM}Образ:         ${IMAGE_SIZE}${NC}                                    "
echo -e "${BOLD}║${NC}  ${DIM}Smoke-тест:    action=${ACTION}, pd_found=${PD_FOUND}${NC}           "
echo -e "${BOLD}║${NC}  ${DIM}Лог:           ${LOG_FILE}${NC}                                      "
echo -e "${BOLD}║${NC}                                                              "
echo -e "${BOLD}║${NC}  📋 ${BOLD}Команды управления:${NC}                                        "
echo -e "${BOLD}║${NC}  ${DIM}Логи:${NC}       docker compose -f $APP_DIR/docker-compose.yml logs -f"
echo -e "${BOLD}║${NC}  ${DIM}Статус:${NC}     docker compose -f $APP_DIR/docker-compose.yml ps    "
echo -e "${BOLD}║${NC}  ${DIM}Рестарт:${NC}    docker compose -f $APP_DIR/docker-compose.yml restart"
echo -e "${BOLD}║${NC}  ${DIM}Остановка:${NC}  docker compose -f $APP_DIR/docker-compose.yml down  "
echo -e "${BOLD}║${NC}                                                              "
echo -e "${BOLD}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""
