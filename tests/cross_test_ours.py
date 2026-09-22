#!/usr/bin/env python3
"""Кросс-тест: тест-кейсы AlfaSonar → pd-proxy."""
import asyncio, aiohttp, json, time, uuid, sys, os
from dataclasses import dataclass, field
from typing import List, Optional

PDPROXY_URL = os.environ.get("PDPROXY_URL", "http://localhost:8080")

@dataclass
class TC:
    id: str
    desc: str
    payload: str
    check_type: str  # "not_contains" | "unchanged" | "error_code"
    not_contains: List[str] = field(default_factory=list)
    contains: List[str] = field(default_factory=list)
    expected_code: int = 200
    known_limitation: bool = False

@dataclass
class TR:
    id: str
    desc: str
    ok: bool
    errors: List[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    known_limitation: bool = False

async def call_pdproxy(session: aiohttp.ClientSession, payload: str, payload_id: str = None) -> tuple:
    """Отправить запрос к pd-proxy."""
    pid = payload_id or str(uuid.uuid4())
    body = {"payload": payload, "payload_id": pid}
    t0 = time.monotonic()
    try:
        async with session.post(f"{PDPROXY_URL}/process", json=body, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            elapsed = (time.monotonic() - t0) * 1000
            data = await resp.json()
            return resp.status, data, elapsed, None
    except Exception as e:
        elapsed = (time.monotonic() - t0) * 1000
        return 0, {}, elapsed, str(e)

def build_alfasonar_tests() -> List[TC]:
    """Тест-кейсы из AlfaSonar integration.py, адаптированные для pd-proxy."""
    tests = []
    
    # === B. Маскирование (позитивные) ===
    
    # ФИО
    tests.append(TC("A-FN-1", "ФИО 3 слова", "Клиент Иванов Иван Иванович",
        "not_contains", not_contains=["Иванов Иван Иванович"]))
    tests.append(TC("A-FN-2", "ФИО 2 слова", "Заявитель Петрова Мария",
        "not_contains", not_contains=["Петрова Мария"]))
    tests.append(TC("A-FN-3", "ФИО UPPER", "ИВАНОВ ИВАН ИВАНОВИЧ",
        "not_contains", not_contains=["ИВАНОВ ИВАН ИВАНОВИЧ"]))
    tests.append(TC("A-FN-4", "ФИО lower (без контекста)", "иванов иван",
        "not_contains", not_contains=["иванов иван"],
        known_limitation=True))  # By design: lowercase ФИО требует контекст
    
    # Держатель карты
    tests.append(TC("A-CH-1", "держатель карты", "Держатель карты: Иванов Иван",
        "not_contains", not_contains=["Иванов Иван"]))
    
    # Дата рождения
    tests.append(TC("A-BD-1", "дата dd.mm.yyyy", "Дата рождения: 12.05.1990",
        "not_contains", not_contains=["12.05.1990"]))
    tests.append(TC("A-BD-2", "дата yyyy.mm.dd", "Дата рождения: 1990.05.12",
        "not_contains", not_contains=["1990.05.12"]))
    tests.append(TC("A-BD-3", "дата yyyy-mm-dd", "Дата рождения: 1990-05-12",
        "not_contains", not_contains=["1990-05-12"]))
    tests.append(TC("A-BD-4", "дата текстом", "Дата рождения: 12 мая 1990",
        "not_contains", not_contains=["12 мая 1990"]))
    tests.append(TC("A-BD-5", "дата + года", "Родился 5 января 1985 года",
        "not_contains", not_contains=["5 января 1985"]))
    
    # Паспорт
    tests.append(TC("A-PP-1", "паспорт словами", "Паспорт: серия 4509 номер 123456",
        "not_contains", not_contains=["4509", "123456"]))
    tests.append(TC("A-PP-2", "паспорт парой", "Паспорт 4509 123456",
        "not_contains", not_contains=["4509 123456"]))
    
    # Водительское удостоверение
    tests.append(TC("A-DL-1", "водительское", "Водительское удостоверение 7701 123456",
        "not_contains", not_contains=["7701 123456"]))
    tests.append(TC("A-DL-2", "в/у", "в/у номер 4509 123456",
        "not_contains", not_contains=["4509 123456"]))
    
    # ИНН
    tests.append(TC("A-IN-1", "ИНН 10", "ИНН: 7707083893",
        "not_contains", not_contains=["7707083893"]))
    tests.append(TC("A-IN-2", "ИНН 12", "ИНН 778252880986",
        "not_contains", not_contains=["778252880986"]))
    
    # Карта
    tests.append(TC("A-CD-1", "карта с пробелами", "Карта: 4532 0151 1283 0366",
        "not_contains", not_contains=["4532 0151 1283 0366"]))
    tests.append(TC("A-CD-2", "карта сплошная", "Карта: 4532015112830366",
        "not_contains", not_contains=["4532015112830366"]))
    
    # CVV
    tests.append(TC("A-CV-1", "CVV (без карты)", "CVV: 123",
        "not_contains", not_contains=["CVV: 123"],
        known_limitation=True))  # By design: CVV без контекста карты не маскируется
    
    # PIN
    tests.append(TC("A-PN-1", "ПИН-код (без карты)", "ПИН-код: 1234",
        "not_contains", not_contains=["ПИН-код: 1234"],
        known_limitation=True))  # By design: ПИН без контекста карты не маскируется
    
    # Email
    tests.append(TC("A-EM-1", "email", "Email: anna.ivanova@mail.ru",
        "not_contains", not_contains=["anna.ivanova@mail.ru"]))
    
    # Телефон
    tests.append(TC("A-PH-1", "телефон +7", "Телефон: +7 999 123-45-67",
        "not_contains", not_contains=["+7 999 123-45-67"]))
    tests.append(TC("A-PH-2", "телефон 8", "Позвоните 8 (999) 123-45-67",
        "not_contains", not_contains=["8 (999) 123-45-67"]))
    
    # Индекс (нет в pd-proxy — нет отдельной категории)
    tests.append(TC("A-IX-1", "почтовый индекс", "Почтовый индекс: 101000",
        "not_contains", not_contains=["101000"], known_limitation=True))
    
    # Адрес
    tests.append(TC("A-AD-1", "адрес полный", "Адрес: г. Москва, ул. Ленина, д. 10, квартира 5",
        "not_contains", not_contains=["Москва", "Ленина"]))
    
    # Гражданство
    tests.append(TC("A-CT-1", "гражданство", "Гражданство: Россия",
        "not_contains", not_contains=["Россия"]))
    
    # Место рождения
    tests.append(TC("A-BP-1", "место рождения", "Место рождения: г. Москва",
        "not_contains", not_contains=["Москва"]))
    
    # Орган выдачи
    tests.append(TC("A-PI-1", "орган выдачи", "Паспорт выдан ОВД Центрального района",
        "not_contains", not_contains=["ОВД Центрального района"]))
    
    # === C. Негативные тесты ===
    tests.append(TC("A-NG-1", "поэт Пушкин", "поэт Александр Пушкин", "unchanged"))
    tests.append(TC("A-NG-2", "адрес отделения банка", "адрес отделения Банка на улице Ленина, 10", "unchanged",
        known_limitation=True))  # У нас может замаскировать как адрес
    tests.append(TC("A-NG-3", "случайное число", "Номер заказа 1234567890", "unchanged"))
    tests.append(TC("A-NG-4", "не-Luhn карта", "Карта 4532 0151 1283 0367", "unchanged"))
    tests.append(TC("A-NG-5", "невалидная дата", "Дата: 34.12.2025", "unchanged"))
    tests.append(TC("A-NG-6", "телефон не-РФ", "Телефон +1 555 123 4567", "unchanged"))
    tests.append(TC("A-NG-7", "email без TLD", "Почта: user@localhost", "unchanged"))
    
    return tests

async def run_test(session: aiohttp.ClientSession, tc: TC) -> TR:
    """Запуск одного теста."""
    status, data, elapsed, error = await call_pdproxy(session, tc.payload)
    
    if error:
        return TR(tc.id, tc.desc, False, errors=[f"Ошибка: {error}"], elapsed_ms=elapsed, known_limitation=tc.known_limitation)
    
    if tc.check_type == "error_code":
        ok = (status == tc.expected_code)
        errors = [] if ok else [f"Ожидали HTTP {tc.expected_code}, получили {status}"]
        return TR(tc.id, tc.desc, ok, errors=errors, elapsed_ms=elapsed, known_limitation=tc.known_limitation)
    
    if status != 200:
        return TR(tc.id, tc.desc, False, errors=[f"HTTP {status}: {data}"], elapsed_ms=elapsed, known_limitation=tc.known_limitation)
    
    result = data.get("result", "")
    errors = []
    
    if tc.check_type == "unchanged":
        if result != tc.payload:
            errors.append(f"Ожидали без изменений, но получили: '{result[:100]}'")
    elif tc.check_type == "not_contains":
        for nc in tc.not_contains:
            if nc in result:
                errors.append(f"Результат содержит '{nc}' (должен был замаскировать)")
        for c in tc.contains:
            if c not in result:
                errors.append(f"Результат не содержит '{c}'")
    
    ok = len(errors) == 0
    return TR(tc.id, tc.desc, ok, errors=errors, elapsed_ms=elapsed, known_limitation=tc.known_limitation)

async def run_all(tests: List[TC]) -> List[TR]:
    """Запуск всех тестов."""
    results = []
    async with aiohttp.ClientSession() as session:
        for tc in tests:
            r = await run_test(session, tc)
            results.append(r)
    return results

def generate_report(results: List[TR], output_path: str):
    """Сгенерировать отчёт."""
    total = len(results)
    known_lim = [r for r in results if r.known_limitation and not r.ok]
    failures = [r for r in results if not r.ok and not r.known_limitation]
    passed = sum(1 for r in results if r.ok)
    
    effective_total = total - len(known_lim)
    pass_rate = (passed / effective_total * 100) if effective_total > 0 else 100.0
    
    lines = []
    lines.append("=" * 70)
    lines.append("  КРОСС-ТЕСТ: тест-кейсы AlfaSonar → pd-proxy")
    lines.append(f"  Сервер: {PDPROXY_URL}")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"  Всего тестов:       {total}")
    lines.append(f"  Пройдено:           {passed}")
    lines.append(f"  Провалено:          {len(failures)}")
    lines.append(f"  Known limitations:  {len(known_lim)}")
    lines.append(f"  Pass rate:          {pass_rate:.1f}% (без KL)")
    lines.append("")
    
    if failures:
        lines.append("-" * 70)
        lines.append("  ПРОВАЛИВШИЕСЯ ТЕСТЫ:")
        lines.append("-" * 70)
        for r in failures:
            lines.append(f"  ❌ {r.id}: {r.desc}")
            for e in r.errors:
                lines.append(f"     {e}")
            lines.append("")
    
    if known_lim:
        lines.append("-" * 70)
        lines.append("  KNOWN LIMITATIONS:")
        lines.append("-" * 70)
        for r in known_lim:
            lines.append(f"  ⚠️  {r.id}: {r.desc}")
            for e in r.errors:
                lines.append(f"     {e}")
        lines.append("")
    
    # Таблица результатов
    lines.append("-" * 70)
    lines.append("  ВСЕ ТЕСТЫ:")
    lines.append("-" * 70)
    for r in results:
        status = "✅" if r.ok else ("⚠️" if r.known_limitation else "❌")
        lines.append(f"  {status} {r.id}: {r.desc} ({r.elapsed_ms:.0f}ms)")
    
    lines.append("")
    lines.append("=" * 70)
    
    report = "\n".join(lines)
    print(report)
    
    with open(output_path, "w") as f:
        f.write(report)
    print(f"\nОтчёт сохранён: {output_path}")

async def main():
    tests = build_alfasonar_tests()
    print(f"🚀 Запуск кросс-теста AlfaSonar → pd-proxy ({len(tests)} тестов)")
    print(f"   Сервер: {PDPROXY_URL}")
    print()
    
    results = await run_all(tests)
    generate_report(results, "cross-test-ours.txt")
    
    # JSON-отчёт
    json_data = {
        "server": PDPROXY_URL,
        "total": len(results),
        "passed": sum(1 for r in results if r.ok),
        "failed": sum(1 for r in results if not r.ok and not r.known_limitation),
        "known_limitations": sum(1 for r in results if r.known_limitation and not r.ok),
        "results": [
            {"id": r.id, "desc": r.desc, "ok": r.ok, "errors": r.errors,
             "elapsed_ms": r.elapsed_ms, "known_limitation": r.known_limitation}
            for r in results
        ]
    }
    with open("cross-test-ours.json", "w") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    
    failed = sum(1 for r in results if not r.ok and not r.known_limitation)
    return 1 if failed > 0 else 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
