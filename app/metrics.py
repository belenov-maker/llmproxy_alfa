"""Prometheus-метрики PD-Proxy.

@business-process Мониторинг производительности и качества детекции
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram, Gauge, generate_latest

# Счётчик обработанных запросов
REQUESTS_TOTAL = Counter(
    "pd_proxy_requests_total",
    "Общее количество обработанных запросов",
    ["action", "system_id"],
)

# Гистограмма задержки обработки
REQUEST_LATENCY = Histogram(
    "pd_proxy_request_latency_seconds",
    "Задержка обработки запроса",
    ["action"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# Счётчик обнаруженных ПДн по категориям
PD_DETECTED = Counter(
    "pd_proxy_pd_detected_total",
    "Количество обнаруженных ПДн",
    ["category"],
)

# FastJev-метрики
JEV_FILTERED = Counter(
    "pd_proxy_jev_filtered_total",
    "Количество ложных срабатываний, отфильтрованных FastJev",
)

JEV_ERRORS = Counter(
    "pd_proxy_jev_errors_total",
    "Количество ошибок FastJev (fail-open)",
)

# Размер хранилища
STORAGE_SIZE = Gauge(
    "pd_proxy_storage_size",
    "Текущее количество записей в хранилище маппингов",
)


def get_metrics() -> bytes:
    """Сериализовать все метрики в формат Prometheus."""
    return generate_latest()
