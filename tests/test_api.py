"""Тесты API endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    """Health-check возвращает status ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_process_masks_pii():
    """POST /process маскирует ПДн в тексте."""
    payload = "Иванов Иван Иванович, паспорт 4509 123456"
    resp = client.post("/process", json={
        "payload": payload,
        "payload_id": "test-001",
        "mode": "fast",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "Иванов" not in data["result"]
    assert "4509" not in data["result"]
    assert data["action"] == "masked"


def test_process_validation_error():
    """POST /process без обязательных полей возвращает 422."""
    resp = client.post("/process", json={})
    assert resp.status_code == 422
