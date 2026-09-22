#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
#  PD-Proxy — запуск интеграционных тестов
# ─────────────────────────────────────────────────────────────────────
#
#  Использование:
#    ./run_tests.sh                          # тесты на http://localhost:8080
#    ./run_tests.sh http://168.100.11.100:8080   # тесты на удалённый сервер
#
#  Переменные окружения:
#    PD_PROXY_URL   — адрес сервера (по умолчанию http://localhost:8080)
#    LOAD_DURATION  — длительность нагрузочного теста, сек (по умолчанию 10)
#    LOAD_CONC      — число параллельных соединений (по умолчанию 100)
#
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv-test"

# Если передан аргумент — используем как URL сервера
if [ "${1:-}" != "" ]; then
    export PD_PROXY_URL="$1"
fi
export PD_PROXY_URL="${PD_PROXY_URL:-http://localhost:8080}"

echo "══════════════════════════════════════════════════════════════"
echo "  PD-Proxy — Интеграционные тесты"
echo "  Сервер: $PD_PROXY_URL"
echo "══════════════════════════════════════════════════════════════"
echo ""

# ── 1. Проверка доступности сервера ──────────────────────────────────
echo "▶ Проверка доступности сервера..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 "$PD_PROXY_URL/health" 2>/dev/null || true)
if [ "$HTTP_CODE" != "200" ]; then
    echo "❌ Сервер $PD_PROXY_URL недоступен (HTTP $HTTP_CODE)"
    echo ""
    echo "  Убедитесь, что PD-Proxy запущен:"
    echo "    docker compose up -d        # Docker"
    echo "    gunicorn app.main:app ...    # Native"
    echo ""
    exit 1
fi
echo "  ✅ Сервер доступен (HTTP 200)"
echo ""

# ── 2. Подготовка виртуального окружения ─────────────────────────────
if [ ! -d "$VENV_DIR" ]; then
    echo "▶ Создание виртуального окружения ($VENV_DIR)..."
    python3 -m venv "$VENV_DIR"
fi

echo "▶ Установка зависимостей..."
"$VENV_DIR/bin/pip" install -q -r "$SCRIPT_DIR/requirements-test.txt"
echo "  ✅ Зависимости установлены"
echo ""

# ── 3. Запуск тестов ─────────────────────────────────────────────────
echo "▶ Запуск тестов..."
echo ""
"$VENV_DIR/bin/python3" "$SCRIPT_DIR/tests/test_server_live.py"
EXIT_CODE=$?

echo ""
echo "══════════════════════════════════════════════════════════════"
if [ $EXIT_CODE -eq 0 ]; then
    echo "  ✅ Все тесты пройдены!"
else
    echo "  ❌ Есть упавшие тесты (код возврата: $EXIT_CODE)"
fi
echo ""
echo "  Отчёты:"
echo "    📄 tests/test-report.txt"
echo "    📄 tests/test-report.json"
echo "══════════════════════════════════════════════════════════════"

exit $EXIT_CODE
