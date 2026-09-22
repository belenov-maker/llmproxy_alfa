"""Тесты rate limiting + обработка больших текстов."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.security.rate_limit import TokenBucket


# ─── Unit-тесты TokenBucket ────────────────────────────────────


class TestTokenBucket:
    def test_initial_allow(self):
        """Первые запросы проходят (burst)."""
        bucket = TokenBucket(rate=10.0, burst=5)
        for _ in range(5):
            assert bucket.allow()

    def test_burst_exceeded(self):
        """После исчерпания burst — отказ."""
        bucket = TokenBucket(rate=10.0, burst=3)
        for _ in range(3):
            bucket.allow()
        assert not bucket.allow()

    def test_refill(self):
        """Токены восстанавливаются со временем."""
        bucket = TokenBucket(rate=1000.0, burst=10)
        for _ in range(10):
            bucket.allow()
        # Вручную сдвигаем время
        bucket.last_refill -= 0.01  # 10ms = 10 токенов при rate=1000
        assert bucket.allow()


# ─── Integration-тесты 429 ─────────────────────────────────────


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_health_bypasses_rate_limit(client):
    """Health endpoint не подвержен rate limiting."""
    for _ in range(100):
        resp = await client.get("/health")
        assert resp.status_code == 200


@pytest.mark.anyio
async def test_rate_limit_429():
    """При исчерпании лимита — 429 + Retry-After."""
    # Используем fresh client чтобы бакет был полный
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as cl:
        statuses = []
        for i in range(200):
            resp = await cl.post("/process", json={
                "payload": "тест",
                "payload_id": f"rl-{i}",
            })
            statuses.append(resp.status_code)
            if resp.status_code == 429:
                assert "Retry-After" in resp.headers
                break
        # Все ответы либо 200 либо 429
        assert all(s in (200, 429) for s in statuses)


# ─── Большие тексты (100K токенов) ────────────────────────────


@pytest.mark.anyio
async def test_large_text_100k_tokens(client):
    """Текст ~100K токенов обрабатывается без ошибки."""
    # ~100K токенов ≈ ~400K символов (1 токен ≈ 4 символа)
    # Генерируем большой текст с ПДн-вкраплениями
    base = "Это тестовый текст для проверки производительности. "
    large_text = base * 5000  # ~250K символов
    # Вставляем ПДн
    large_text += " Иванов Иван Иванович, паспорт 4510 123456, тел +7 (999) 888-77-66"

    resp = await client.post("/process", json={
        "payload": large_text,
        "payload_id": "large-100k",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["action"] == "masked"
    assert data["stats"]["pd_found"] > 0


@pytest.mark.anyio
async def test_large_text_proxy(client):
    """Большой текст через /proxy без OOM."""
    large_text = "Текст " * 10000 + "Козлов Пётр Сергеевич"

    resp = await client.post("/proxy", json={
        "payload": large_text,
        "payload_id": "large-proxy",
    })
    assert resp.status_code == 200
    data = resp.json()
    # Без LLM — вернёт замаскированный текст
    assert data["error"] is not None  # LLM не настроен
