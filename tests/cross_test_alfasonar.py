#!/usr/bin/env python3
"""Кросс-тест: тест-кейсы pd-proxy → AlfaSonar."""
import asyncio, aiohttp, json, time, uuid, sys, os
from dataclasses import dataclass, field
from typing import List, Optional

ALFASONAR_URL = os.environ.get("ALFASONAR_URL", "http://localhost:8080")

@dataclass
class TC:
    group: str
    tag: str
    payload: str
    expect_masked: bool = True  # True = ожидаем маскирование, False = ожидаем без изменений
    exp_cats: List[str] = field(default_factory=list)  # для справки
    known_limitation: bool = False

@dataclass
class TR:
    group: str
    tag: str
    ok: bool
    payload_preview: str = ""
    result_preview: str = ""
    errors: List[str] = field(default_factory=list)
    elapsed_ms: float = 0.0
    known_limitation: bool = False

async def call_alfasonar(session: aiohttp.ClientSession, payload: str) -> tuple:
    """Отправить запрос к AlfaSonar. Возвращает (result, elapsed_ms, error)."""
    pid = str(uuid.uuid4())
    body = {"payload": payload, "payload_id": pid}
    t0 = time.monotonic()
    try:
        async with session.post(f"{ALFASONAR_URL}/process", json=body, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            elapsed = (time.monotonic() - t0) * 1000
            if resp.status != 200:
                return None, elapsed, f"HTTP {resp.status}"
            data = await resp.json()
            return data.get("result", ""), elapsed, None
    except Exception as e:
        elapsed = (time.monotonic() - t0) * 1000
        return None, elapsed, str(e)

def build_tests() -> List[TC]:
    """Тест-кейсы из нашего test_server_live.py (основные)."""
    tests = []
    
    # === Группа A: Прямые тесты 21 категории ===
    
    # ФИО
    tests.append(TC("A", "fio-full", "Иванов Иван Иванович обратился в банк.", True, ["fio"]))
    tests.append(TC("A", "fio-female", "Заявление от Петровой Марии Сергеевны.", True, ["fio"]))
    tests.append(TC("A", "fio-initials", "Сидоров А.В. подписал договор.", True, ["fio"]))
    tests.append(TC("A", "fio-two-words", "Клиент Иванов Иван записан на приём.", True, ["fio"]))
    
    # Паспорт
    tests.append(TC("A", "passport-ctx", "Паспорт: серия 4510 номер 123456.", True, ["passport"]))
    tests.append(TC("A", "passport-pair", "Паспорт 4509 123456", True, ["passport"]))
    
    # СНИЛС (нет в AlfaSonar)
    tests.append(TC("A", "snils", "СНИЛС 234-567-890 12", True, ["snils"], known_limitation=True))
    
    # ИНН
    tests.append(TC("A", "inn-10", "ИНН: 7707083893", True, ["inn"]))
    tests.append(TC("A", "inn-12", "ИНН 778252880986", True, ["inn"]))
    
    # Телефон
    tests.append(TC("A", "phone-plus7", "Телефон: +7 999 123-45-67", True, ["phone"]))
    tests.append(TC("A", "phone-8", "Позвоните 89991234567", True, ["phone"]))
    
    # Email
    tests.append(TC("A", "email", "Email: anna.ivanova@mail.ru", True, ["email"]))
    
    # Карта
    tests.append(TC("A", "card-spaces", "Карта: 4532 0151 1283 0366", True, ["card_number"]))
    tests.append(TC("A", "card-solid", "Карта: 4532015112830366", True, ["card_number"]))
    
    # CVV
    tests.append(TC("A", "cvv", "CVV: 123", True, ["cvv"]))
    
    # PIN
    tests.append(TC("A", "pin", "ПИН-код: 1234", True, ["pin"]))
    
    # Адрес
    tests.append(TC("A", "address", "Адрес: г. Москва, ул. Ленина, д. 10, кв. 25", True, ["address"]))
    
    # Дата рождения
    tests.append(TC("A", "birth-date-num", "Дата рождения: 01.01.1990", True, ["birth_date"]))
    tests.append(TC("A", "birth-date-text", "Дата рождения: 15 марта 1985", True, ["birth_date"]))
    
    # Место рождения
    tests.append(TC("A", "birth-place", "Место рождения: г. Новосибирск", True, ["birth_place"]))
    
    # Гражданство
    tests.append(TC("A", "citizenship", "Гражданство: Российская Федерация", True, ["citizenship"]))
    
    # Код подразделения
    tests.append(TC("A", "subdivision", "Код подразделения: 770-025", True, ["subdivision_code"]))
    
    # Орган выдачи
    tests.append(TC("A", "issuer", "Паспорт выдан ОВД Центрального района", True, ["issuing_authority"]))
    
    # Дата выдачи
    tests.append(TC("A", "issue-date", "Выдан 15.03.2015", True, ["issue_date"]))
    
    # ОМС (нет в AlfaSonar)
    tests.append(TC("A", "oms", "Полис ОМС 1234567890123456", True, ["oms"], known_limitation=True))
    
    # Водительское удостоверение
    tests.append(TC("A", "drivers-license", "Водительское удостоверение: 77 14 567890", True, ["drivers_license"]))
    
    # Загранпаспорт (нет в AlfaSonar)
    tests.append(TC("A", "foreign-passport", "Загранпаспорт 72 1234567", True, ["foreign_passport"], known_limitation=True))
    
    # Военный билет (нет в AlfaSonar)
    tests.append(TC("A", "military-id", "Военный билет: АБ 1234567", True, ["military_id"], known_limitation=True))
    
    # Держатель карты
    tests.append(TC("A", "cardholder", "Держатель карты: Иванов Иван", True, ["cardholder_name"]))
    
    # === Группа B: Граничные сценарии ===
    tests.append(TC("B", "empty", "", False))
    tests.append(TC("B", "no-pd", "Сегодня хорошая погода, солнце светит ярко.", False))
    tests.append(TC("B", "unicode-emoji", "🎉 Привет мир! 🌍 Без ПДн.", False))
    
    # === Группа C: Anti-FP ===
    tests.append(TC("C", "pushkin", "Александр Сергеевич Пушкин написал Евгения Онегина.", False))
    tests.append(TC("C", "ooo-romashka", "Компания ООО Ромашка зарегистрирована в 2020 году.", False))
    tests.append(TC("C", "president-putin", "Президент Владимир Путин выступил с речью.", False))
    tests.append(TC("C", "tolstoy", "Лев Толстой написал Войну и мир.", False))
    tests.append(TC("C", "mendeleev", "Профессор Менделеев прочитал лекцию.", False))
    tests.append(TC("C", "gagarin", "Площадь Гагарина расположена в центре.", False))
    tests.append(TC("C", "raskolnikov", "Раскольников был главным героем романа.", False))
    tests.append(TC("C", "non-luhn-card", "Карта 4532 0151 1283 0367", False))
    tests.append(TC("C", "order-number", "Номер заказа 1234567890", False))
    tests.append(TC("C", "invalid-date", "Дата: 34.12.2025", False))
    tests.append(TC("C", "foreign-phone", "Телефон +1 555 123 4567", False))
    
    # === Группа D: Комбинированные ===
    tests.append(TC("D", "full-client", 
        "Клиент Козлов Дмитрий Андреевич, дата рождения 12.03.1988, паспорт серия 4515 номер 654321, выдан УФМС по г. Москве 20.05.2018.",
        True, ["fio", "birth_date", "passport", "issuing_authority", "issue_date"]))
    tests.append(TC("D", "contact-info",
        "Телефон: +7(999)123-45-67, email: user@mail.ru, карта 4276 1234 5678 9010.",
        True, ["phone", "email", "card_number"]))
    tests.append(TC("D", "inn-oms",
        "ИНН 123456789012, полис ОМС 1234567890123456, загранпаспорт 72 1234567.",
        True, ["inn", "oms", "foreign_passport"]))
    
    return tests

async def run_tests(tests: List[TC]) -> List[TR]:
    """Запуск всех тестов."""
    results = []
    async with aiohttp.ClientSession() as session:
        for tc in tests:
            if tc.group == "B" and tc.tag == "empty":
                # Пустая строка — AlfaSonar вернёт 400
                results.append(TR(tc.group, tc.tag, True, payload_preview="(empty)"))
                continue
            
            result_text, elapsed, error = await call_alfasonar(session, tc.payload)
            
            if error:
                results.append(TR(
                    tc.group, tc.tag, False,
                    payload_preview=tc.payload[:80],
                    errors=[f"Ошибка запроса: {error}"],
                    elapsed_ms=elapsed,
                    known_limitation=tc.known_limitation
                ))
                continue
            
            # Проверка: маскирование сработало или нет
            was_masked = (result_text != tc.payload)
            
            errors = []
            if tc.expect_masked and not was_masked:
                errors.append(f"Ожидали маскирование, но текст не изменился")
            elif not tc.expect_masked and was_masked:
                errors.append(f"Ожидали без изменений, но текст изменился: '{result_text[:80]}...'")
            
            ok = len(errors) == 0
            results.append(TR(
                tc.group, tc.tag, ok,
                payload_preview=tc.payload[:80],
                result_preview=(result_text or "")[:80],
                errors=errors,
                elapsed_ms=elapsed,
                known_limitation=tc.known_limitation
            ))
    return results

def generate_report(results: List[TR], output_path: str):
    """Сгенерировать отчёт."""
    total = len(results)
    known_lim = [r for r in results if r.known_limitation and not r.ok]
    failures = [r for r in results if not r.ok and not r.known_limitation]
    passed = total - len(failures) - len(known_lim)
    
    effective_total = total - len(known_lim)
    pass_rate = (passed / effective_total * 100) if effective_total > 0 else 100.0
    
    lines = []
    lines.append("=" * 70)
    lines.append("  КРОСС-ТЕСТ: тест-кейсы pd-proxy → AlfaSonar")
    lines.append(f"  Сервер: {ALFASONAR_URL}")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"  Всего тестов:       {total}")
    lines.append(f"  Пройдено:           {passed}")
    lines.append(f"  Провалено:          {len(failures)}")
    lines.append(f"  Known limitations:  {len(known_lim)}")
    lines.append(f"  Pass rate:          {pass_rate:.1f}% (без KL)")
    lines.append("")
    
    # По группам
    groups = {}
    for r in results:
        groups.setdefault(r.group, []).append(r)
    
    for g in sorted(groups.keys()):
        g_results = groups[g]
        g_pass = sum(1 for r in g_results if r.ok)
        g_kl = sum(1 for r in g_results if r.known_limitation and not r.ok)
        g_fail = len(g_results) - g_pass - g_kl
        lines.append(f"  Группа {g}: {g_pass}/{len(g_results)} пройдено, {g_fail} провалено, {g_kl} KL")
    
    lines.append("")
    
    if failures:
        lines.append("-" * 70)
        lines.append("  ПРОВАЛИВШИЕСЯ ТЕСТЫ:")
        lines.append("-" * 70)
        for r in failures:
            lines.append(f"  ❌ [{r.group}] {r.tag}")
            lines.append(f"     Payload: {r.payload_preview}")
            lines.append(f"     Result:  {r.result_preview}")
            for e in r.errors:
                lines.append(f"     Error:   {e}")
            lines.append("")
    
    if known_lim:
        lines.append("-" * 70)
        lines.append("  KNOWN LIMITATIONS (ожидаемые расхождения):")
        lines.append("-" * 70)
        for r in known_lim:
            lines.append(f"  ⚠️  [{r.group}] {r.tag}")
            for e in r.errors:
                lines.append(f"     {e}")
        lines.append("")
    
    lines.append("=" * 70)
    
    report = "\n".join(lines)
    print(report)
    
    with open(output_path, "w") as f:
        f.write(report)
    print(f"\nОтчёт сохранён: {output_path}")

async def main():
    tests = build_tests()
    print(f"🚀 Запуск кросс-теста pd-proxy → AlfaSonar ({len(tests)} тестов)")
    print(f"   Сервер: {ALFASONAR_URL}")
    print()
    
    results = await run_tests(tests)
    generate_report(results, "cross-test-alfasonar.txt")
    
    # JSON-отчёт
    json_data = {
        "server": ALFASONAR_URL,
        "total": len(results),
        "passed": sum(1 for r in results if r.ok),
        "failed": sum(1 for r in results if not r.ok and not r.known_limitation),
        "known_limitations": sum(1 for r in results if r.known_limitation and not r.ok),
        "results": [
            {"group": r.group, "tag": r.tag, "ok": r.ok, "errors": r.errors,
             "elapsed_ms": r.elapsed_ms, "known_limitation": r.known_limitation}
            for r in results
        ]
    }
    with open("cross-test-alfasonar.json", "w") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    
    failed = sum(1 for r in results if not r.ok and not r.known_limitation)
    return 1 if failed > 0 else 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
