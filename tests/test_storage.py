"""Тесты InMemoryStorage."""

import time

import pytest

from app.storage.memory import InMemoryStorage, MaskingEntry


def _entry(pid: str = "test-001", fwd: dict | None = None) -> MaskingEntry:
    return MaskingEntry(
        payload_id=pid,
        forward_map=fwd or {"Иванов": "[FIO_1]"},
        reverse_map={"[FIO_1]": "Иванов"} if fwd is None else {},
        payload_hash="abc123",
        masked_result="[FIO_1] обратился",
    )


class TestInMemoryStorage:
    def test_put_and_get(self):
        """Базовое сохранение и получение."""
        s = InMemoryStorage()
        e = _entry()
        s.put(e)
        got = s.get("test-001")
        assert got is not None
        assert got.payload_id == "test-001"
        assert got.forward_map == {"Иванов": "[FIO_1]"}

    def test_get_missing(self):
        """Несуществующий ключ → None."""
        s = InMemoryStorage()
        assert s.get("missing") is None

    def test_ttl_expiry(self):
        """Просроченная запись не возвращается."""
        s = InMemoryStorage(ttl=1)
        e = _entry()
        e.created_at = time.time() - 2  # Создана 2 секунды назад
        s.put(e)
        # Обходим put() который ставит created_at = now
        s._store["test-001"].created_at = time.time() - 2
        assert s.get("test-001") is None

    def test_lru_eviction(self):
        """При превышении max_size вытесняется самый старый."""
        s = InMemoryStorage(max_size=3)
        s.put(_entry("a"))
        s.put(_entry("b"))
        s.put(_entry("c"))
        assert s.size() == 3

        # Добавляем 4-й — "a" вытесняется
        s.put(_entry("d"))
        assert s.size() == 3
        assert s.get("a") is None
        assert s.get("d") is not None

    def test_lru_access_updates_order(self):
        """Доступ к записи обновляет LRU-порядок."""
        s = InMemoryStorage(max_size=3)
        s.put(_entry("a"))
        s.put(_entry("b"))
        s.put(_entry("c"))

        # Обращаемся к "a" — теперь "b" самый старый
        s.get("a")
        s.put(_entry("d"))

        assert s.get("b") is None  # "b" вытеснен
        assert s.get("a") is not None  # "a" сохранён

    def test_access_count(self):
        """access_count увеличивается при каждом get."""
        s = InMemoryStorage()
        s.put(_entry())
        s.get("test-001")
        s.get("test-001")
        entry = s.get("test-001")
        assert entry is not None
        assert entry.access_count == 3  # 3 get() вызова

    def test_idempotent_check_same_hash(self):
        """check_idempotent: тот же payload_hash → возвращает запись."""
        s = InMemoryStorage()
        e = _entry()
        e.payload_hash = s._hash_payload("hello")
        s.put(e)
        result = s.check_idempotent("test-001", "hello")
        assert result is not None

    def test_idempotent_check_different_hash(self):
        """check_idempotent: разный payload_hash → None."""
        s = InMemoryStorage()
        e = _entry()
        e.payload_hash = s._hash_payload("hello")
        s.put(e)
        result = s.check_idempotent("test-001", "world")
        assert result is None

    def test_cleanup_expired(self):
        """cleanup_expired удаляет просроченные записи."""
        s = InMemoryStorage(ttl=1)
        s.put(_entry("a"))
        s.put(_entry("b"))
        # Принудительно устариваем
        for e in s._store.values():
            e.created_at = time.time() - 2
        removed = s.cleanup_expired()
        assert removed == 2
        assert s.size() == 0

    def test_update_existing(self):
        """Обновление существующей записи перезаписывает данные."""
        s = InMemoryStorage()
        s.put(_entry("x"))
        new = _entry("x")
        new.forward_map = {"Петров": "[FIO_2]"}
        s.put(new)
        got = s.get("x")
        assert got is not None
        assert got.forward_map == {"Петров": "[FIO_2]"}
        assert s.size() == 1  # Не дублируется

    def test_clear(self):
        """clear() очищает хранилище."""
        s = InMemoryStorage()
        s.put(_entry("a"))
        s.put(_entry("b"))
        s.clear()
        assert s.size() == 0

    def test_has(self):
        """has() проверяет наличие с учётом TTL."""
        s = InMemoryStorage()
        s.put(_entry("a"))
        assert s.has("a") is True
        assert s.has("b") is False
