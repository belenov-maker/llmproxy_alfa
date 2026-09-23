"""Тесты структурного логирования и аудита.

Проверяем:
- X-Request-ID в response headers
- Аудит-логи /process (masked/unmasked/cached)
- Request-logging middleware
- Rate limit логирование
"""

from __future__ import annotations

import json
import logging

import pytest
from starlette.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    return TestClient(app)


class TestRequestId:
    """X-Request-ID header в ответах."""

    def test_process_has_request_id(self, client):
        r = client.post("/process", json={
            "payload_id": "rid-test-1",
            "payload": "Иванов Иван Иванович",
        })
        assert r.status_code == 200
        rid = r.headers.get("x-request-id")
        assert rid is not None
        assert len(rid) == 12  # hex UUID4 prefix

    def test_health_has_request_id(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.headers.get("x-request-id") is not None

    def test_request_ids_are_unique(self, client):
        r1 = client.get("/health")
        r2 = client.get("/health")
        assert r1.headers["x-request-id"] != r2.headers["x-request-id"]


class TestAuditLogs:
    """Аудит-логи /process."""

    def test_masked_audit_log(self, client, caplog):
        """Маскирование логирует event=pd_processed, action=masked."""
        with caplog.at_level(logging.INFO, logger="app.main"):
            r = client.post("/process", json={
                "payload_id": "audit-mask-1",
                "payload": "Иванов Иван Иванович, тел. +7 912 345-67-89",
            })
        assert r.status_code == 200
        # Ищем аудит-запись
        audit_records = [
            rec for rec in caplog.records
            if hasattr(rec, "event") and rec.event == "pd_processed"  # type: ignore[attr-defined]
        ]
        assert len(audit_records) >= 1
        rec = audit_records[0]
        assert rec.action == "masked"  # type: ignore[attr-defined]
        assert rec.payload_id == "audit-mask-1"  # type: ignore[attr-defined]
        assert rec.pd_count >= 1  # type: ignore[attr-defined]

    def test_cached_audit_log(self, client, caplog):
        """Кэшированный повтор логирует action=cached."""
        # Первый запрос — маскирование
        client.post("/process", json={
            "payload_id": "audit-cache-1",
            "payload": "Иванов Иван Иванович",
        })
        # Второй запрос — кэш
        with caplog.at_level(logging.INFO, logger="app.main"):
            r = client.post("/process", json={
                "payload_id": "audit-cache-1",
                "payload": "Иванов Иван Иванович",
            })
        assert r.status_code == 200
        assert r.json()["action"] == "cached"
        audit_records = [
            rec for rec in caplog.records
            if hasattr(rec, "event")
            and rec.event == "pd_processed"  # type: ignore[attr-defined]
            and getattr(rec, "action", "") == "cached"
        ]
        assert len(audit_records) >= 1

    def test_unmasked_audit_log(self, client, caplog):
        """Демаскирование логирует action=unmasked."""
        # Первый запрос — маскирование
        client.post("/process", json={
            "payload_id": "audit-unmask-1",
            "payload": "Иванов Иван Иванович",
        })
        # Второй запрос с другим payload — демаскирование
        with caplog.at_level(logging.INFO, logger="app.main"):
            r = client.post("/process", json={
                "payload_id": "audit-unmask-1",
                "payload": "Ответ с [FIO_1] внутри",
            })
        assert r.status_code == 200
        assert r.json()["action"] == "unmasked"
        audit_records = [
            rec for rec in caplog.records
            if hasattr(rec, "event")
            and rec.event == "pd_processed"  # type: ignore[attr-defined]
            and getattr(rec, "action", "") == "unmasked"
        ]
        assert len(audit_records) >= 1


class TestRequestLoggerMiddleware:
    """Middleware логирует HTTP-запросы."""

    def test_process_request_logged(self, client, caplog):
        """POST /process логируется middleware."""
        with caplog.at_level(logging.INFO, logger="app.middleware.request_logger"):
            client.post("/process", json={
                "payload_id": "mw-test-1",
                "payload": "Тестовый текст",
            })
        http_records = [
            rec for rec in caplog.records
            if hasattr(rec, "event") and rec.event == "http_request"  # type: ignore[attr-defined]
        ]
        assert len(http_records) >= 1
        rec = http_records[0]
        assert rec.method == "POST"  # type: ignore[attr-defined]
        assert rec.path == "/process"  # type: ignore[attr-defined]
        assert rec.status == 200  # type: ignore[attr-defined]
        assert rec.latency_ms > 0  # type: ignore[attr-defined]

    def test_health_not_logged(self, client, caplog):
        """GET /health НЕ логируется middleware (skip path)."""
        with caplog.at_level(logging.INFO, logger="app.middleware.request_logger"):
            client.get("/health")
        http_records = [
            rec for rec in caplog.records
            if hasattr(rec, "event") and rec.event == "http_request"  # type: ignore[attr-defined]
        ]
        assert len(http_records) == 0
