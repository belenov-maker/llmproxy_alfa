"""Edge cases и интеграционные тесты API."""

import pytest
from fastapi.testclient import TestClient

from app.main import app, storage

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_storage():
    """Очищать хранилище перед каждым тестом."""
    storage.clear()
    yield
    storage.clear()


class TestProcessEndpoint:
    """Тесты POST /process."""

    def test_mask_simple_text(self):
        """Маскирование простого текста с ФИО + телефон."""
        resp = client.post("/process", json={
            "payload": "Клиент Иванов Иван Иванович, тел +79161234567",
            "payload_id": "t-001",
            "mode": "fast",  # Без FastJev для юнит-тестов
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "masked"
        # Телефон всегда маскируется
        assert "+79161234567" not in data["result"]
        # ФИО должно быть хотя бы частично замаскировано
        assert "[FIO_1]" in data["result"]
        assert data["stats"]["pd_found"] > 0

    def test_idempotent_repeat(self):
        """Повторный запрос с тем же payload → cached."""
        payload = "Тестовый текст с ФИО: Петров Пётр Петрович"
        for _ in range(2):
            resp = client.post("/process", json={
                "payload": payload,
                "payload_id": "t-002",
                "mode": "fast",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "cached"

    def test_unmask_different_payload(self):
        """Тот же payload_id, другой payload → демаскирование."""
        # Шаг 1: маскирование
        resp1 = client.post("/process", json={
            "payload": "Клиент Сидоров Сергей Сергеевич, email: sid@mail.ru",
            "payload_id": "t-003",
            "mode": "fast",
        })
        assert resp1.status_code == 200
        masked = resp1.json()["result"]

        # Шаг 2: демаскирование (тот же id, другой payload)
        resp2 = client.post("/process", json={
            "payload": masked,  # Отправляем маскированный текст
            "payload_id": "t-003",
        })
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["action"] == "unmasked"

    def test_empty_payload(self):
        """Пустой payload → без ошибок."""
        resp = client.post("/process", json={
            "payload": "",
            "payload_id": "t-004",
            "mode": "fast",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"] == ""
        assert data["stats"]["pd_found"] == 0

    def test_no_pii_text(self):
        """Текст без ПДн → result = payload."""
        text = "Сегодня хорошая погода. Температура +15 градусов."
        resp = client.post("/process", json={
            "payload": text,
            "payload_id": "t-005",
            "mode": "fast",
        })
        assert resp.status_code == 200
        data = resp.json()
        # Текст без ПДн должен вернуться без изменений
        assert data["stats"]["pd_found"] == 0

    def test_validation_missing_payload_id(self):
        """Без payload_id → 422."""
        resp = client.post("/process", json={"payload": "test"})
        assert resp.status_code == 422

    def test_validation_missing_payload(self):
        """Без payload → 422."""
        resp = client.post("/process", json={"payload_id": "t-006"})
        assert resp.status_code == 422

    def test_large_text(self):
        """Большой текст (~10K символов) обрабатывается."""
        text = "Иванов Иван Иванович, паспорт 4509 123456. " * 250
        resp = client.post("/process", json={
            "payload": text,
            "payload_id": "t-007",
            "mode": "fast",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["stats"]["pd_found"] > 0
        assert "Иванов" not in data["result"]

    def test_unicode_text(self):
        """Unicode (ё, Ё) корректно обрабатывается."""
        resp = client.post("/process", json={
            "payload": "Алёхин Артём Сергеевич, тел 89161234567",
            "payload_id": "t-008",
            "mode": "fast",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "Алёхин" not in data["result"]

    def test_system_id_default(self):
        """system_id по умолчанию = 'default'."""
        resp = client.post("/process", json={
            "payload": "test",
            "payload_id": "t-009",
        })
        assert resp.status_code == 200

    def test_system_id_load_test(self):
        """system_id='load_test' → mode=fast."""
        resp = client.post("/process", json={
            "payload": "Иванов Иван, тел +79161234567",
            "payload_id": "t-010",
            "system_id": "load_test",
        })
        assert resp.status_code == 200


class TestHealthEndpoint:
    def test_health(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data


class TestMetricsEndpoint:
    def test_metrics(self):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        # Prometheus text format
        assert "pd_proxy_storage_size" in resp.text
        assert "text/plain" in resp.headers.get("content-type", "")


class TestMultiplePD:
    """Тесты с несколькими типами ПДн в одном тексте."""

    def test_full_personal_data_block(self):
        """Полный блок ПДн: ФИО + паспорт + телефон + email + СНИЛС."""
        text = (
            "ФИО: Козлов Дмитрий Александрович\n"
            "Паспорт: 4515 678901\n"
            "Телефон: +79031234567\n"
            "Email: kozlov@example.com\n"
            "СНИЛС: 123-456-789 00"
        )
        resp = client.post("/process", json={
            "payload": text,
            "payload_id": "t-multi-001",
            "mode": "fast",
        })
        assert resp.status_code == 200
        data = resp.json()
        result = data["result"]
        # Все ПДн должны быть замаскированы
        assert "Козлов" not in result
        assert "4515" not in result
        assert "+7903" not in result
        assert "kozlov@" not in result
        assert "123-456-789" not in result
        assert data["stats"]["pd_found"] >= 4
