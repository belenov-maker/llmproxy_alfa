"""In-memory хранилище маппингов маскирования.

Хранит payload_id → {original → placeholder} для демаскирования.
TTL + LRU-вытеснение при превышении max_size.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field


@dataclass
class MaskingEntry:
    """Запись маппинга маскирования."""

    payload_id: str
    # Маппинг: original_value → placeholder (например, "Иванов Иван" → "[FIO_1]")
    forward_map: dict[str, str] = field(default_factory=dict)
    # Обратный маппинг: placeholder → original_value
    reverse_map: dict[str, str] = field(default_factory=dict)
    # Хэш исходного payload для идемпотентности
    payload_hash: str = ""
    # Маскированный результат (кэш)
    masked_result: str | None = None
    # Метаданные
    created_at: float = 0.0
    accessed_at: float = 0.0
    access_count: int = 0


class InMemoryStorage:
    """Thread-safe in-memory хранилище с TTL и LRU.

    Attributes:
        ttl: Время жизни записи в секундах (по умолчанию 3600).
        max_size: Максимальное количество записей (по умолчанию 100_000).
    """

    def __init__(self, ttl: int = 3600, max_size: int = 100_000) -> None:
        self.ttl = ttl
        self.max_size = max_size
        self._store: OrderedDict[str, MaskingEntry] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _hash_payload(payload: str) -> str:
        """SHA-256 хэш payload для идемпотентности."""
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def get(self, payload_id: str) -> MaskingEntry | None:
        """Получить запись по payload_id. Обновляет LRU и access_count."""
        with self._lock:
            entry = self._store.get(payload_id)
            if entry is None:
                return None
            # Проверка TTL
            if time.time() - entry.created_at > self.ttl:
                del self._store[payload_id]
                return None
            # LRU: переместить в конец
            self._store.move_to_end(payload_id)
            entry.accessed_at = time.time()
            entry.access_count += 1
            return entry

    def put(self, entry: MaskingEntry) -> None:
        """Сохранить запись. Вытесняет старейшую при превышении max_size."""
        now = time.time()
        entry.created_at = entry.created_at or now
        entry.accessed_at = now
        with self._lock:
            # Обновление существующей
            if entry.payload_id in self._store:
                self._store.move_to_end(entry.payload_id)
                self._store[entry.payload_id] = entry
                return
            # Вытеснение LRU
            while len(self._store) >= self.max_size:
                self._store.popitem(last=False)
            self._store[entry.payload_id] = entry

    def has(self, payload_id: str) -> bool:
        """Проверить наличие записи (с учётом TTL)."""
        return self.get(payload_id) is not None

    def check_idempotent(self, payload_id: str, payload: str) -> MaskingEntry | None:
        """Проверить идемпотентность: если payload_id существует и hash совпадает — вернуть кэш."""
        entry = self.get(payload_id)
        if entry is None:
            return None
        current_hash = self._hash_payload(payload)
        if entry.payload_hash == current_hash:
            return entry  # Идемпотентный повтор
        return None  # payload_id тот же, но payload другой → демаскирование

    def size(self) -> int:
        """Текущее количество записей."""
        with self._lock:
            return len(self._store)

    def cleanup_expired(self) -> int:
        """Удалить все просроченные записи. Возвращает количество удалённых."""
        now = time.time()
        removed = 0
        with self._lock:
            expired = [
                pid for pid, entry in self._store.items()
                if now - entry.created_at > self.ttl
            ]
            for pid in expired:
                del self._store[pid]
                removed += 1
        return removed

    def clear(self) -> None:
        """Очистить хранилище."""
        with self._lock:
            self._store.clear()
