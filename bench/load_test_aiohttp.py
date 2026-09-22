#!/usr/bin/env python3
"""Нагрузочный тест pd-proxy — aiohttp (быстрее httpx).

Сценарий: POST /process с уникальными payload_id.
Цель: RPS ≥ 1000, p99 ≤ 1с.
"""

import asyncio
import time
import random
import json
import statistics
import sys
from dataclasses import dataclass, field

import aiohttp

BASE_URL = "http://127.0.0.1:8080"

NAMES = [
    "Иванов Иван Иванович",
    "Петрова Мария Сергеевна",
    "Козлов Алексей Дмитриевич",
    "Сидорова Елена Петровна",
    "Волков Дмитрий Андреевич",
]
PHONES = ["+7 (999) 888-77-66", "+7 (916) 123-45-67", "8-800-555-35-35"]
PASSPORTS = ["4510 123456", "4511 654321", "4600 987654"]
EMAILS = ["ivan@mail.ru", "maria@yandex.ru", "info@company.com"]
INNS = ["123456789012", "770123456789"]


@dataclass
class Stats:
    latencies: list[float] = field(default_factory=list)
    errors: int = 0
    total: int = 0
    rate_limited: int = 0
    start_time: float = 0.0
    end_time: float = 0.0


def make_payload(worker_id: int, iteration: int) -> dict:
    text = (
        f"Клиент: {random.choice(NAMES)}, паспорт {random.choice(PASSPORTS)}, "
        f"тел {random.choice(PHONES)}, email {random.choice(EMAILS)}, "
        f"ИНН {random.choice(INNS)}. Просьба оформить заявку."
    )
    return {
        "payload": text,
        "payload_id": f"bench-{worker_id}-{iteration}-{time.monotonic_ns()}",
    }


async def worker(
    session: aiohttp.ClientSession,
    worker_id: int,
    stats: Stats,
    stop_event: asyncio.Event,
):
    iteration = 0
    url = f"{BASE_URL}/process"
    while not stop_event.is_set():
        body = make_payload(worker_id, iteration)
        t0 = time.monotonic()
        try:
            async with session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                elapsed = (time.monotonic() - t0) * 1000
                stats.total += 1
                if resp.status == 200:
                    stats.latencies.append(elapsed)
                elif resp.status == 429:
                    stats.total -= 1
                    stats.rate_limited += 1
                    await asyncio.sleep(0.02)
                else:
                    stats.errors += 1
                    stats.latencies.append(elapsed)
        except Exception:
            stats.total += 1
            stats.errors += 1
        iteration += 1


def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_data) else f
    d = k - f
    return sorted_data[f] + d * (sorted_data[c] - sorted_data[f])


async def run_test(concurrency: int, duration_s: int):
    print(f"🚀 Нагрузочный тест pd-proxy (aiohttp)")
    print(f"   Concurrency: {concurrency} VU")
    print(f"   Duration: {duration_s}s")
    print(f"   Target: {BASE_URL}/process")
    print()

    stats = Stats()
    stop_event = asyncio.Event()

    connector = aiohttp.TCPConnector(
        limit=concurrency + 20,
        keepalive_timeout=30,
    )
    async with aiohttp.ClientSession(connector=connector) as session:
        # Warm-up
        body = make_payload(0, 0)
        async with session.post(f"{BASE_URL}/process", json=body) as resp:
            await resp.read()

        stats.start_time = time.monotonic()

        tasks = [
            asyncio.create_task(worker(session, i, stats, stop_event))
            for i in range(concurrency)
        ]

        for elapsed in range(duration_s):
            await asyncio.sleep(1)
            current_rps = stats.total / (time.monotonic() - stats.start_time)
            if (elapsed + 1) % 10 == 0:
                print(
                    f"   [{elapsed+1:3d}s] requests={stats.total}, "
                    f"rps={current_rps:.0f}, errors={stats.errors}, "
                    f"rate_limited={stats.rate_limited}"
                )

        stop_event.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        stats.end_time = time.monotonic()

    return stats


def print_report(stats: Stats, concurrency: int, duration_s: int) -> tuple[dict, str]:
    wall_time = stats.end_time - stats.start_time
    rps = stats.total / wall_time if wall_time > 0 else 0
    error_pct = (stats.errors / stats.total * 100) if stats.total > 0 else 0

    p50 = percentile(stats.latencies, 50)
    p90 = percentile(stats.latencies, 90)
    p95 = percentile(stats.latencies, 95)
    p99 = percentile(stats.latencies, 99)
    avg = statistics.mean(stats.latencies) if stats.latencies else 0
    max_lat = max(stats.latencies) if stats.latencies else 0
    min_lat = min(stats.latencies) if stats.latencies else 0

    rps_pass = rps >= 1000
    p99_pass = p99 <= 1000
    verdict = "✅ PASS" if (rps_pass and p99_pass) else "❌ FAIL"

    report = f"""# Отчёт о нагрузочном тестировании pd-proxy

## Параметры
- **Concurrency:** {concurrency} VU
- **Duration:** {duration_s}s
- **Target:** POST /process (уникальный payload_id на каждый запрос)
- **Wall time:** {wall_time:.1f}s
- **Client:** aiohttp (async)

## Результаты

| Метрика | Значение | Критерий | Статус |
|---------|----------|----------|--------|
| **RPS** | {rps:.0f} | ≥ 1000 | {"✅" if rps_pass else "❌"} |
| **p99 latency** | {p99:.1f} ms | ≤ 1000 ms | {"✅" if p99_pass else "❌"} |
| Всего запросов | {stats.total} | — | — |
| Ошибки | {stats.errors} ({error_pct:.2f}%) | < 1% | {"✅" if error_pct < 1 else "❌"} |
| Rate Limited (429) | {stats.rate_limited} | — | — |

## Latency Distribution

| Percentile | Latency (ms) |
|-----------|-------------|
| min | {min_lat:.1f} |
| p50 | {p50:.1f} |
| p90 | {p90:.1f} |
| p95 | {p95:.1f} |
| p99 | {p99:.1f} |
| max | {max_lat:.1f} |
| avg | {avg:.1f} |

## Вердикт: {verdict}
"""

    print(report)

    result = {
        "rps": round(rps),
        "total_requests": stats.total,
        "errors": stats.errors,
        "error_pct": round(error_pct, 2),
        "rate_limited": stats.rate_limited,
        "latency_ms": {
            "min": round(min_lat, 1),
            "p50": round(p50, 1),
            "p90": round(p90, 1),
            "p95": round(p95, 1),
            "p99": round(p99, 1),
            "max": round(max_lat, 1),
            "avg": round(avg, 1),
        },
        "pass": rps_pass and p99_pass,
        "verdict": verdict,
    }
    return result, report


async def main():
    concurrency = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 30

    stats = await run_test(concurrency, duration)
    result, report = print_report(stats, concurrency, duration)

    with open("bench/results.json", "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print("📄 JSON: bench/results.json")

    with open("bench/REPORT.md", "w") as f:
        f.write(report)
    print("📄 Отчёт: bench/REPORT.md")


if __name__ == "__main__":
    asyncio.run(main())
