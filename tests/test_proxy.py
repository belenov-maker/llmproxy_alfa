"""Тесты для POST /proxy — LLM-прокси с маскированием/демаскированием."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ─── Базовые тесты ─────────────────────────────────────────────


@pytest.mark.anyio
async def test_proxy_no_llm_configured(client):
    """Без настроенного LLM — вернёт замаскированный текст + ошибку."""
    resp = await client.post("/proxy", json={
        "payload": "Иванов Иван Иванович, тел. +7 (999) 123-45-67",
        "payload_id": "proxy-test-1",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["payload_id"] == "proxy-test-1"
    # Без LLM — result = masked input
    assert "[FIO_" in data["result"] or "[PHONE_" in data["result"]
    assert data["error"] is not None
    assert "LLM не настроен" in data["error"]


@pytest.mark.anyio
async def test_proxy_masks_pd_before_llm(client):
    """ПДн маскируются перед отправкой в LLM."""
    with patch("app.proxy.llm_proxy.settings") as mock_settings:
        mock_settings.llm_base_url = "http://fake-llm"
        mock_settings.llm_api_key = "fake-key"
        mock_settings.llm_model = "test-model"
        mock_settings.jev_enabled = False

        # Мокаем httpx-вызов к LLM
        with patch("app.proxy.llm_proxy._call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = ("Ответ про [FIO_1]: всё хорошо", 100.0)

            resp = await client.post("/proxy", json={
                "payload": "Обработай данные клиента Петров Пётр Петрович, телефон +7 (912) 555-44-33",
                "payload_id": "proxy-test-2",
            })
            assert resp.status_code == 200
            data = resp.json()

            # Проверяем, что LLM получил замаскированный текст (без ПДн)
            call_args = mock_llm.call_args
            messages = call_args[0][0]
            user_msg = messages[-1]["content"]
            # В замаскированном тексте не должно быть настоящих ПДн
            assert "Петров" not in user_msg
            assert "+7 (912)" not in user_msg
            # Но должны быть плейсхолдеры
            assert "[FIO_" in user_msg or "[PHONE_" in user_msg


@pytest.mark.anyio
async def test_proxy_unmasks_llm_response(client):
    """Ответ LLM демаскируется перед возвратом клиенту."""
    with patch("app.proxy.llm_proxy.settings") as mock_settings:
        mock_settings.llm_base_url = "http://fake-llm"
        mock_settings.llm_api_key = "fake-key"
        mock_settings.llm_model = "test-model"
        mock_settings.jev_enabled = False

        with patch("app.proxy.llm_proxy._call_llm", new_callable=AsyncMock) as mock_llm:
            # LLM вернёт ответ с плейсхолдерами
            mock_llm.return_value = ("Клиент [FIO_1] подтверждён, звоните на [PHONE_1]", 50.0)

            resp = await client.post("/proxy", json={
                "payload": "Проверь клиента Сидоров Андрей Михайлович, тел +7 (903) 111-22-33",
                "payload_id": "proxy-test-3",
            })
            assert resp.status_code == 200
            data = resp.json()

            # Демаскированный результат должен содержать оригинальные данные
            result = data["result"]
            assert "Сидоров Андрей Михайлович" in result
            assert "+7 (903) 111-22-33" in result


@pytest.mark.anyio
async def test_proxy_no_pd_passthrough(client):
    """Текст без ПДн проходит через LLM без изменений."""
    with patch("app.proxy.llm_proxy.settings") as mock_settings:
        mock_settings.llm_base_url = "http://fake-llm"
        mock_settings.llm_api_key = "fake-key"
        mock_settings.llm_model = "test-model"
        mock_settings.jev_enabled = False

        with patch("app.proxy.llm_proxy._call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = ("Ответ LLM: погода хорошая", 30.0)

            resp = await client.post("/proxy", json={
                "payload": "Какая сегодня погода?",
                "payload_id": "proxy-test-4",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["result"] == "Ответ LLM: погода хорошая"
            assert data["stats"]["pd_found"] == 0


@pytest.mark.anyio
async def test_proxy_with_system_prompt(client):
    """Системный промпт передаётся в LLM."""
    with patch("app.proxy.llm_proxy.settings") as mock_settings:
        mock_settings.llm_base_url = "http://fake-llm"
        mock_settings.llm_api_key = "fake-key"
        mock_settings.llm_model = "test-model"
        mock_settings.jev_enabled = False

        with patch("app.proxy.llm_proxy._call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = ("OK", 10.0)

            resp = await client.post("/proxy", json={
                "payload": "Привет",
                "payload_id": "proxy-test-5",
                "llm_prompt": "Ты — помощник по финансам.",
            })
            assert resp.status_code == 200

            # Проверяем что system prompt передан
            call_args = mock_llm.call_args
            messages = call_args[0][0]
            assert len(messages) == 2
            assert messages[0]["role"] == "system"
            assert messages[0]["content"] == "Ты — помощник по финансам."


@pytest.mark.anyio
async def test_proxy_stats_returned(client):
    """Статистика обработки возвращается в ответе."""
    resp = await client.post("/proxy", json={
        "payload": "Паспорт 4510 123456, ИНН 123456789012",
        "payload_id": "proxy-test-6",
    })
    assert resp.status_code == 200
    data = resp.json()
    stats = data["stats"]
    assert stats is not None
    assert stats["pd_found"] > 0
    assert stats["regex_ms"] >= 0
    assert stats["total_ms"] > 0


@pytest.mark.anyio
async def test_proxy_llm_error_returns_error_field(client):
    """При ошибке LLM — error поле заполнено."""
    with patch("app.proxy.llm_proxy.settings") as mock_settings:
        mock_settings.llm_base_url = "http://fake-llm"
        mock_settings.llm_api_key = "fake-key"
        mock_settings.llm_model = "test-model"
        mock_settings.jev_enabled = False

        with patch("app.proxy.llm_proxy._call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("Connection refused")

            resp = await client.post("/proxy", json={
                "payload": "Текст",
                "payload_id": "proxy-test-7",
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["error"] is not None
            assert "Connection refused" in data["error"]


# ─── Тест на отсутствие утечки ПДн ─────────────────────────────


@pytest.mark.anyio
async def test_proxy_pd_never_sent_to_llm(client):
    """Критический тест: ПДн НИКОГДА не утекают в LLM."""
    pd_text = (
        "Клиент: Козлов Дмитрий Сергеевич, "
        "паспорт 4515 678901, "
        "ИНН 770912345678, "
        "телефон +7 (999) 888-77-66, "
        "email dmitry.kozlov@example.com, "
        "адрес: г. Москва, ул. Ленина, д. 15, кв. 42"
    )

    with patch("app.proxy.llm_proxy.settings") as mock_settings:
        mock_settings.llm_base_url = "http://fake-llm"
        mock_settings.llm_api_key = "fake-key"
        mock_settings.llm_model = "test-model"
        mock_settings.jev_enabled = False

        captured_messages = []

        async def capture_llm(messages, model):
            captured_messages.append(messages)
            return ("Обработано", 10.0)

        with patch("app.proxy.llm_proxy._call_llm", side_effect=capture_llm):
            resp = await client.post("/proxy", json={
                "payload": pd_text,
                "payload_id": "proxy-leak-test",
            })
            assert resp.status_code == 200

            # Проверяем что LLM НЕ получил ПДн
            assert len(captured_messages) == 1
            user_msg = captured_messages[0][-1]["content"]

            # Ни одно реальное ПДн не должно быть в тексте
            pd_values = [
                "Козлов Дмитрий Сергеевич",
                "4515 678901",
                "770912345678",
                "+7 (999) 888-77-66",
                "dmitry.kozlov@example.com",
                "ул. Ленина, д. 15, кв. 42",
            ]
            for pd_val in pd_values:
                assert pd_val not in user_msg, f"УТЕЧКА ПДн в LLM: {pd_val!r}"

            # Должны быть плейсхолдеры
            assert "[" in user_msg and "]" in user_msg
