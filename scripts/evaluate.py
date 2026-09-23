#!/usr/bin/env python3
"""
Оценка точности (precision/recall/F1) pd-proxy на аннотированном корпусе.

Метод (чёрный ящик, POST /process):
1. Отправляем текст → получаем маскированный result + stats (pd_found, categories).
2. Из stats.categories извлекаем мультимножество предсказанных типов.
3. Сравниваем с ground truth по типам (мультимножественное сопоставление):
   - TP = тип есть и в predicted, и в expected.
   - FP = тип в predicted, но не в expected.
   - FN = тип в expected, но не в predicted.
4. Дополнительно: для negative-сэмплов проверяем, что pd_found == 0.
5. Демаскирование: отправляем masked с тем же payload_id → exact-match с оригиналом.

Запуск:
    python3 scripts/evaluate.py [--url http://localhost:8080] [--corpus eval/corpus.json]

Env: PD_PROXY_URL (default http://localhost:8080), CORPUS (default eval/corpus.json).
Вывод: таблица precision/recall/F1 по типам + JSON-отчёт в eval/results/.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from collections import Counter
from pathlib import Path

try:
    import requests
except ImportError:
    print("❌ requests не установлен. pip install requests")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Маппинг типов: AlfaSonar ↔ pd-proxy
# ---------------------------------------------------------------------------
TYPE_MAP_TO_OURS = {
    "FULL_NAME": "fio",
    "BIRTH_DATE": "birth_date",
    "BIRTH_PLACE": "birth_place",
    "PASSPORT_SERIES_NUMBER": "passport",
    "CITIZENSHIP": "citizenship",
    "PASSPORT_ISSUER": "issuing_authority",
    "DEPARTMENT_CODE": "subdivision_code",
    "PASSPORT_ISSUE_DATE": "issue_date",
    "DRIVER_LICENSE": "drivers_license",
    "ADDRESS": "address",
    "ADDRESS_COUNTRY": "address",
    "ADDRESS_INDEX": "address",
    "ADDRESS_CITY": "address",
    "ADDRESS_STREET": "address",
    "ADDRESS_HOUSE": "address",
    "ADDRESS_APARTMENT": "address",
    "EMAIL": "email",
    "PHONE": "phone",
    "INN": "inn",
    "CARD_NUMBER": "card_number",
    "CVV": "cvv",
    "CARD_PIN": "pin",
    "CARDHOLDER_NAME": "cardholder_name",
    "SNILS": "snils",
    "OMS": "oms",
    "FOREIGN_PASSPORT": "foreign_passport",
    "MILITARY_ID": "military_id",
}

TYPE_MAP_TO_DISPLAY = {v: k for k, v in TYPE_MAP_TO_OURS.items()}


def normalize_type(t: str) -> str:
    """Нормализовать тип из corpus.json к нашей схеме."""
    return TYPE_MAP_TO_OURS.get(t, t.lower())


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def process_request(
    session: requests.Session,
    url: str,
    payload: str,
    payload_id: str,
    system_id: str = "default",
    timeout: float = 30.0,
) -> tuple[int, dict, float]:
    """POST /process и вернуть (status_code, body, ms)."""
    t0 = time.perf_counter()
    resp = session.post(
        f"{url}/process",
        json={
            "payload": payload,
            "payload_id": payload_id,
            "system_id": system_id,
        },
        timeout=timeout,
    )
    ms = (time.perf_counter() - t0) * 1000
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text[:500]}
    return resp.status_code, body, ms


# ---------------------------------------------------------------------------
# Мультимножественное сопоставление типов
# ---------------------------------------------------------------------------

def match_categories(
    predicted: list[str], expected: list[str],
) -> tuple[dict[str, int], list[str], list[str]]:
    """Сопоставить predicted vs expected по типам (multiset matching).

    Returns:
        tp_by_type: {type: count} — совпавшие
        fp_types: list — лишние predicted
        fn_types: list — пропущенные expected
    """
    pred_counter = Counter(predicted)
    exp_counter = Counter(expected)

    all_types = set(pred_counter.keys()) | set(exp_counter.keys())

    tp_by_type: dict[str, int] = {}
    fp_types: list[str] = []
    fn_types: list[str] = []

    for t in all_types:
        p_count = pred_counter.get(t, 0)
        e_count = exp_counter.get(t, 0)
        tp = min(p_count, e_count)
        fp = p_count - tp
        fn = e_count - tp

        if tp > 0:
            tp_by_type[t] = tp
        fp_types.extend([t] * fp)
        fn_types.extend([t] * fn)

    return tp_by_type, fp_types, fn_types


# ---------------------------------------------------------------------------
# Основной цикл
# ---------------------------------------------------------------------------

def evaluate(url: str, corpus_path: str, results_dir: str) -> dict:
    """Запустить оценку на корпусе и вернуть отчёт."""
    with open(corpus_path, encoding="utf-8") as f:
        corpus = json.load(f)

    session = requests.Session()

    # Прогрев
    for i in range(3):
        process_request(
            session, url,
            f"Прогрев {i}. Клиент Иванов Иван Иванович.",
            f"eval-warmup-{uuid.uuid4().hex[:8]}",
        )

    per_type: dict[str, dict[str, int]] = {}
    total = {"tp": 0, "fp": 0, "fn": 0}
    details = []
    unmask_ok = 0
    unmask_total = 0
    latencies = []
    neg_fp = 0  # FP на negative-сэмплах

    print(f"\n🔬 Оценка pd-proxy на корпусе ({len(corpus)} образцов)")
    print(f"   URL: {url}")
    print(f"   Корпус: {corpus_path}\n")

    for _idx, sample in enumerate(corpus):
        text = sample["text"]
        expected = sample.get("expected", [])
        sid = sample["id"]
        is_negative = sample.get("negative", False)
        pid = f"eval-{uuid.uuid4().hex[:12]}"

        # --- Маскирование ---
        code, body, ms = process_request(session, url, text, pid)
        latencies.append(ms)

        if code != 200:
            print(f"  ❌ [{sid}] HTTP {code}: {body}")
            continue

        masked = body.get("result", "")
        stats = body.get("stats", {})
        predicted_cats: list[str] = stats.get("categories", [])
        pd_found: int = stats.get("pd_found", 0)

        # Нормализуем ожидаемые типы
        expected_types: list[str] = [normalize_type(ex["type"]) for ex in expected]

        # --- Negative check ---
        if is_negative:
            if pd_found > 0:
                neg_fp += 1
                # Все predicted = FP
                for cat in predicted_cats:
                    per_type.setdefault(cat, {"tp": 0, "fp": 0, "fn": 0})["fp"] += 1
                total["fp"] += len(predicted_cats)
                print(f"  🔸 [{sid}] {ms:.0f}ms negative, но pd_found={pd_found} FP={predicted_cats}")
            else:
                pass  # Верно: negative + pd_found==0

            details.append({
                "id": sid, "text": text[:100], "negative": True,
                "ms": round(ms, 1), "tp": [], "fp": predicted_cats if pd_found > 0 else [],
                "fn": [], "unmask_exact": None,
                "pd_found": pd_found, "stats_cats": predicted_cats,
            })
            continue

        # --- Positive: мультимножественное сопоставление ---
        tp_by_type, fp_types, fn_types = match_categories(predicted_cats, expected_types)

        # Обновляем счётчики
        for t, c in tp_by_type.items():
            per_type.setdefault(t, {"tp": 0, "fp": 0, "fn": 0})["tp"] += c
        for t in fp_types:
            per_type.setdefault(t, {"tp": 0, "fp": 0, "fn": 0})["fp"] += 1
        for t in fn_types:
            per_type.setdefault(t, {"tp": 0, "fp": 0, "fn": 0})["fn"] += 1

        total["tp"] += sum(tp_by_type.values())
        total["fp"] += len(fp_types)
        total["fn"] += len(fn_types)

        # --- Демаскирование ---
        unmask_exact = None
        if expected:
            unmask_total += 1
            code2, body2, _ms2 = process_request(session, url, masked, pid)
            unmask_exact = (code2 == 200 and body2.get("result") == text)
            unmask_ok += 1 if unmask_exact else 0
            if not unmask_exact:
                print(f"  ⚠ [{sid}] Демаскирование не совпало")

        # Прогресс
        if fn_types or fp_types:
            status = "⚠" if fn_types else "🔹"
            detail_str = f"  {status} [{sid}] {ms:.0f}ms"
            if fn_types:
                detail_str += f" FN={fn_types}"
            if fp_types:
                detail_str += f" FP={fp_types}"
            print(detail_str)

        details.append({
            "id": sid, "text": text[:100], "negative": False,
            "ms": round(ms, 1),
            "tp": list(tp_by_type.keys()),
            "fp": fp_types, "fn": fn_types,
            "unmask_exact": unmask_exact,
            "pd_found": pd_found,
            "stats_cats": predicted_cats,
        })

    # ------------------------------------------------------------------
    # Отчёт
    # ------------------------------------------------------------------
    print("\n" + "=" * 90)
    print(f"{'Тип':<28} {'TP':>4} {'FP':>4} {'FN':>4} {'Precision':>10} {'Recall':>8} {'F1':>8}")
    print("=" * 90)

    def calc_f1(tp: int, fp: int, fn: int) -> float:
        p = tp / (tp + fp) if tp + fp else 1.0
        r = tp / (tp + fn) if tp + fn else 1.0
        return (2 * p * r / (p + r)) if p + r else 0.0

    rows = []
    for tname in sorted(per_type.keys()):
        st = per_type[tname]
        p = st["tp"] / (st["tp"] + st["fp"]) if st["tp"] + st["fp"] else None
        r = st["tp"] / (st["tp"] + st["fn"]) if st["tp"] + st["fn"] else None
        f = calc_f1(st["tp"], st["fp"], st["fn"])
        rows.append((tname, st, p, r, f))

    for tname, st, p, r, f in rows:
        display_name = TYPE_MAP_TO_DISPLAY.get(tname, tname.upper())
        print(
            f"{display_name:<28} {st['tp']:>4} {st['fp']:>4} {st['fn']:>4} "
            f"{(f'{p:.3f}' if p is not None else '    -'):>10} "
            f"{(f'{r:.3f}' if r is not None else '   -'):>8} "
            f"{f:>8.3f}"
        )

    P = total["tp"] / (total["tp"] + total["fp"]) if total["tp"] + total["fp"] else 1.0
    R = total["tp"] / (total["tp"] + total["fn"]) if total["tp"] + total["fn"] else 1.0
    F = 2 * P * R / (P + R) if P + R else 0.0

    print("-" * 90)
    print(
        f"{'ИТОГО':<28} {total['tp']:>4} {total['fp']:>4} {total['fn']:>4} "
        f"{P:>10.3f} {R:>8.3f} {F:>8.3f}"
    )
    print(f"\nДемаскирование (exact-match): {unmask_ok}/{unmask_total}")
    if neg_fp:
        print(f"⚠ Negative FP: {neg_fp} (ложные срабатывания на чистых текстах)")

    if latencies:
        latencies_sorted = sorted(latencies)
        p50 = latencies_sorted[len(latencies_sorted) // 2]
        p99 = latencies_sorted[int(len(latencies_sorted) * 0.99)]
        print(f"Задержка: median={p50:.1f}ms, p99={p99:.1f}ms")

    # JSON-отчёт
    report = {
        "url": url,
        "corpus": corpus_path,
        "samples": len(details),
        "total": total,
        "precision": round(P, 4),
        "recall": round(R, 4),
        "f1": round(F, 4),
        "unmask_exact": {"ok": unmask_ok, "total": unmask_total},
        "negative_fp": neg_fp,
        "latency": {
            "median_ms": round(p50, 1) if latencies else 0,
            "p99_ms": round(p99, 1) if latencies else 0,
        },
        "per_type": {
            t: {
                **st,
                "precision": round(st["tp"] / (st["tp"] + st["fp"]), 4)
                    if st["tp"] + st["fp"] else None,
                "recall": round(st["tp"] / (st["tp"] + st["fn"]), 4)
                    if st["tp"] + st["fn"] else None,
                "f1": round(calc_f1(st["tp"], st["fp"], st["fn"]), 4),
            }
            for t, st in per_type.items()
        },
        "details": details,
    }

    os.makedirs(results_dir, exist_ok=True)
    out_path = os.path.join(results_dir, "eval_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n📊 Отчёт: {out_path}")

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Оценка качества pd-proxy (precision/recall/F1)"
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("PD_PROXY_URL", "http://localhost:8080"),
        help="URL pd-proxy (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--corpus",
        default=os.environ.get("CORPUS", "eval/corpus.json"),
        help="Путь к corpus.json",
    )
    parser.add_argument(
        "--results-dir",
        default="eval/results",
        help="Каталог для JSON-отчёта",
    )
    args = parser.parse_args()

    if not Path(args.corpus).exists():
        print(f"❌ Корпус не найден: {args.corpus}")
        print("   Создайте файл eval/corpus.json с аннотированными примерами.")
        print('   Формат: [{"id": "fn-01", "text": "...", '
              '"expected": [{"type": "fio", "start": 0, "end": 10}]}]')
        sys.exit(1)

    evaluate(args.url, args.corpus, args.results_dir)


if __name__ == "__main__":
    main()
