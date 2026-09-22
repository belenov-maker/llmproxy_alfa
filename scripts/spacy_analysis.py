#!/usr/bin/env python3
"""SpaCy-анализ качества маскирования PD-Proxy.

Сравнивает результаты regex-детектора с SpaCy NER (ru_core_news_lg).
Выявляет:
  - False Negatives (ПДн пропущенные regex, но найденные SpaCy)
  - False Positives (regex нашёл, но SpaCy считает не-ПДн)
  - Согласованные детекции (оба нашли)

Генерирует отчёт с precision/recall/F1 по категориям.

Запуск:
    cd pd-proxy
    .venv/bin/python3 scripts/spacy_analysis.py
"""

from __future__ import annotations

import json
import sys
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import spacy
from app.engine.detector import detect, PDMatch


# ---------------------------------------------------------------------------
# Маппинг SpaCy NER → PD-Proxy категории
# ---------------------------------------------------------------------------

SPACY_TO_PD: dict[str, str] = {
    "PER": "fio",           # Персоны
    "PERSON": "fio",        # Персоны (альтернативный тег)
    "LOC": "address",       # Локации → адрес
    "GPE": "address",       # Геополитические сущности → адрес
    "ORG": "_org",          # Организации (нет прямого аналога, исключаем)
    "DATE": "_date",        # Даты (может быть birth_date или issue_date)
    "CARDINAL": "_number",  # Числа (может быть что угодно)
    "MONEY": "_skip",       # Деньги
    "PERCENT": "_skip",     # Проценты
    "TIME": "_skip",        # Время
    "QUANTITY": "_skip",    # Количество
    "ORDINAL": "_skip",     # Порядковые числа
    "NORP": "_skip",        # Национальности/группы
    "FAC": "address",       # Сооружения → адрес
    "PRODUCT": "_skip",     # Продукты
    "EVENT": "_skip",       # События
    "WORK_OF_ART": "_skip", # Произведения
    "LAW": "_skip",         # Законы
    "LANGUAGE": "_skip",    # Языки
}

# Категории PD-Proxy, которые SpaCy не может детектировать (структурные данные)
REGEX_ONLY_CATEGORIES = {
    "passport", "snils", "inn", "card_number", "cvv", "pin",
    "phone", "email", "oms", "drivers_license", "foreign_passport",
    "military_id", "subdivision_code", "cardholder_name",
}


# ---------------------------------------------------------------------------
# Тестовые данные
# ---------------------------------------------------------------------------

@dataclass
class TestSample:
    """Тестовый образец с текстом и ожидаемыми ПДн."""
    text: str
    description: str
    expected_pd: list[dict[str, str]]  # [{"category": ..., "value": ...}]


def build_test_samples() -> list[TestSample]:
    """Набор тестовых текстов с разнообразными ПДн."""
    return [
        # --- Группа 1: Чистые ФИО ---
        TestSample(
            text="Иванов Иван Иванович обратился в банк.",
            description="Полное ФИО",
            expected_pd=[{"category": "fio", "value": "Иванов Иван Иванович"}],
        ),
        TestSample(
            text="Заявление от Петровой Марии Сергеевны.",
            description="Полное ФИО женское",
            expected_pd=[{"category": "fio", "value": "Петровой Марии Сергеевны"}],
        ),
        TestSample(
            text="Сидоров А.В. подписал договор.",
            description="ФИО с инициалами",
            expected_pd=[{"category": "fio", "value": "Сидоров А.В."}],
        ),
        TestSample(
            text="Директор Козлов Дмитрий Петрович назначил совещание.",
            description="ФИО в контексте должности",
            expected_pd=[{"category": "fio", "value": "Козлов Дмитрий Петрович"}],
        ),

        # --- Группа 2: ФИО + паспортные данные ---
        TestSample(
            text="Иванов Иван Иванович, паспорт серия 4510 номер 123456.",
            description="ФИО + паспорт",
            expected_pd=[
                {"category": "fio", "value": "Иванов Иван Иванович"},
                {"category": "passport", "value": "4510 123456"},
            ],
        ),
        TestSample(
            text="Паспортные данные: серия 4510 номер 654321, выдан ОВД района Тверской 15.03.2015.",
            description="Паспорт + орган выдачи + дата выдачи",
            expected_pd=[
                {"category": "passport", "value": "4510 654321"},
                {"category": "issuing_authority", "value": "ОВД района Тверской"},
                {"category": "issue_date", "value": "15.03.2015"},
            ],
        ),

        # --- Группа 3: Контактные данные ---
        TestSample(
            text="Телефон: +7 (495) 123-45-67, email: test@example.com",
            description="Телефон + email",
            expected_pd=[
                {"category": "phone", "value": "+7 (495) 123-45-67"},
                {"category": "email", "value": "test@example.com"},
            ],
        ),
        TestSample(
            text="Звоните по номеру 8-916-555-12-34.",
            description="Телефон формат 8-xxx",
            expected_pd=[{"category": "phone", "value": "8-916-555-12-34"}],
        ),

        # --- Группа 4: Финансовые данные ---
        TestSample(
            text="Номер карты: 4276 1234 5678 9012, CVV: 123",
            description="Банковская карта + CVV",
            expected_pd=[
                {"category": "card_number", "value": "4276 1234 5678 9012"},
                {"category": "cvv", "value": "123"},
            ],
        ),
        TestSample(
            text="ИНН: 770123456789",
            description="ИНН физлица",
            expected_pd=[{"category": "inn", "value": "770123456789"}],
        ),
        TestSample(
            text="СНИЛС: 123-456-789 00",
            description="СНИЛС",
            expected_pd=[{"category": "snils", "value": "123-456-789 00"}],
        ),

        # --- Группа 5: Адреса ---
        TestSample(
            text="Адрес: г. Москва, ул. Тверская, д. 15, кв. 42.",
            description="Полный адрес",
            expected_pd=[{"category": "address", "value": "г. Москва, ул. Тверская, д. 15, кв. 42"}],
        ),
        TestSample(
            text="Проживает по адресу: Московская обл., г. Подольск, ул. Ленина, д. 5.",
            description="Адрес с областью",
            expected_pd=[{"category": "address", "value": "Московская обл., г. Подольск, ул. Ленина, д. 5"}],
        ),

        # --- Группа 6: Даты рождения ---
        TestSample(
            text="Дата рождения: 15.06.1990",
            description="Дата рождения числовая",
            expected_pd=[{"category": "birth_date", "value": "15.06.1990"}],
        ),
        TestSample(
            text="Родился 25 декабря 1985 года.",
            description="Дата рождения текстом",
            expected_pd=[{"category": "birth_date", "value": "25 декабря 1985"}],
        ),

        # --- Группа 7: Anti-FP (ложные срабатывания) ---
        TestSample(
            text="Александр Сергеевич Пушкин написал Евгения Онегина.",
            description="Anti-FP: известная личность",
            expected_pd=[],  # Не должно маскироваться
        ),
        TestSample(
            text="Компания ООО Ромашка зарегистрирована в 2020 году.",
            description="Anti-FP: название организации",
            expected_pd=[],
        ),
        TestSample(
            text="Президент Владимир Путин выступил с речью.",
            description="Anti-FP: публичная фигура",
            expected_pd=[],
        ),
        TestSample(
            text="В городе Санкт-Петербург проходит фестиваль.",
            description="Anti-FP: топоним без контекста адреса",
            expected_pd=[],
        ),
        TestSample(
            text="Температура воздуха составила 25 градусов.",
            description="Anti-FP: числовые данные",
            expected_pd=[],
        ),

        # --- Группа 8: Комбинированные ---
        TestSample(
            text=(
                "Клиент Козлов Дмитрий Андреевич, дата рождения 12.03.1988, "
                "паспорт серия 4515 номер 987654, СНИЛС 111-222-333 44, "
                "проживает: г. Москва, ул. Арбат, д. 10, кв. 5. "
                "Телефон: +7 (916) 111-22-33, email: kozlov@mail.ru"
            ),
            description="Полный набор ПДн клиента",
            expected_pd=[
                {"category": "fio", "value": "Козлов Дмитрий Андреевич"},
                {"category": "birth_date", "value": "12.03.1988"},
                {"category": "passport", "value": "4515 987654"},
                {"category": "snils", "value": "111-222-333 44"},
                {"category": "address", "value": "г. Москва, ул. Арбат, д. 10, кв. 5"},
                {"category": "phone", "value": "+7 (916) 111-22-33"},
                {"category": "email", "value": "kozlov@mail.ru"},
            ],
        ),
        TestSample(
            text=(
                "Заёмщик: Морозова Елена Викторовна, ИНН 501234567890, "
                "полис ОМС 1234567890123456, загранпаспорт 72 1234567."
            ),
            description="ФИО + ИНН + ОМС + загранпаспорт",
            expected_pd=[
                {"category": "fio", "value": "Морозова Елена Викторовна"},
                {"category": "inn", "value": "501234567890"},
                {"category": "oms", "value": "1234567890123456"},
                {"category": "foreign_passport", "value": "72 1234567"},
            ],
        ),

        # --- Группа 9: Сложные контексты ---
        TestSample(
            text="Место рождения: г. Новосибирск, гражданство: Российская Федерация.",
            description="Место рождения + гражданство",
            expected_pd=[
                {"category": "birth_place", "value": "г. Новосибирск"},
                {"category": "citizenship", "value": "Российская Федерация"},
            ],
        ),
        TestSample(
            text="Код подразделения: 770-025, выдан УФМС по г. Москве 20.05.2018.",
            description="Код подразделения + орган выдачи + дата",
            expected_pd=[
                {"category": "subdivision_code", "value": "770-025"},
                {"category": "issuing_authority", "value": "УФМС по г. Москве"},
                {"category": "issue_date", "value": "20.05.2018"},
            ],
        ),
        TestSample(
            text="Водительское удостоверение: 77 14 567890.",
            description="Водительское удостоверение",
            expected_pd=[{"category": "drivers_license", "value": "77 14 567890"}],
        ),
        TestSample(
            text="Военный билет: АБ 1234567.",
            description="Военный билет",
            expected_pd=[{"category": "military_id", "value": "АБ 1234567"}],
        ),
    ]


# ---------------------------------------------------------------------------
# SpaCy анализатор
# ---------------------------------------------------------------------------

@dataclass
class SpacyEntity:
    """Сущность, найденная SpaCy."""
    text: str
    label: str
    start: int
    end: int
    pd_category: str  # Маппинг в PD-Proxy категорию


@dataclass
class ComparisonResult:
    """Результат сравнения regex vs SpaCy для одного образца."""
    sample: TestSample
    regex_matches: list[PDMatch]
    spacy_entities: list[SpacyEntity]
    # Анализ
    true_positives: list[str]       # Категории, найденные обоими
    false_negatives_regex: list[str]  # SpaCy нашёл, regex пропустил
    false_positives_regex: list[str]  # Regex нашёл, но это не ПДн (по ожиданиям)
    regex_only: list[str]            # Regex нашёл, SpaCy не может (структурные)
    elapsed_regex_ms: float = 0.0
    elapsed_spacy_ms: float = 0.0


def analyze_with_spacy(nlp, text: str) -> list[SpacyEntity]:
    """Анализ текста SpaCy NER."""
    doc = nlp(text)
    entities = []
    for ent in doc.ents:
        pd_cat = SPACY_TO_PD.get(ent.label_, "_unknown")
        entities.append(SpacyEntity(
            text=ent.text,
            label=ent.label_,
            start=ent.start_char,
            end=ent.end_char,
            pd_category=pd_cat,
        ))
    return entities


def compare_results(
    sample: TestSample,
    regex_matches: list[PDMatch],
    spacy_entities: list[SpacyEntity],
    elapsed_regex_ms: float,
    elapsed_spacy_ms: float,
) -> ComparisonResult:
    """Сравнить результаты regex и SpaCy."""

    expected_cats = {ep["category"] for ep in sample.expected_pd}
    regex_cats = {m.category for m in regex_matches}
    spacy_cats = {e.pd_category for e in spacy_entities if not e.pd_category.startswith("_")}

    # True Positives: regex нашёл то, что ожидалось
    true_positives = list(expected_cats & regex_cats)

    # False Negatives: ожидалось, но regex не нашёл
    fn_regex = list(expected_cats - regex_cats)

    # False Positives: regex нашёл лишнее (не в ожиданиях)
    # Но только для не-Anti-FP тестов
    if sample.expected_pd:
        fp_regex = list(regex_cats - expected_cats)
    else:
        # Anti-FP тест: всё что regex нашёл — false positive
        fp_regex = list(regex_cats)

    # Regex-only: структурные данные, которые SpaCy не может найти
    regex_only = list(regex_cats & REGEX_ONLY_CATEGORIES)

    return ComparisonResult(
        sample=sample,
        regex_matches=regex_matches,
        spacy_entities=spacy_entities,
        true_positives=true_positives,
        false_negatives_regex=fn_regex,
        false_positives_regex=fp_regex,
        regex_only=regex_only,
        elapsed_regex_ms=elapsed_regex_ms,
        elapsed_spacy_ms=elapsed_spacy_ms,
    )


# ---------------------------------------------------------------------------
# Метрики
# ---------------------------------------------------------------------------

@dataclass
class CategoryMetrics:
    """Метрики по категории."""
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) > 0 else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


def compute_metrics(results: list[ComparisonResult]) -> dict[str, CategoryMetrics]:
    """Вычислить precision/recall/F1 по категориям для regex-детектора."""
    metrics: dict[str, CategoryMetrics] = {}

    for result in results:
        expected_cats = {ep["category"] for ep in result.sample.expected_pd}
        regex_cats = {m.category for m in result.regex_matches}

        all_cats = expected_cats | regex_cats
        for cat in all_cats:
            if cat not in metrics:
                metrics[cat] = CategoryMetrics()

            in_expected = cat in expected_cats
            in_regex = cat in regex_cats

            if in_expected and in_regex:
                metrics[cat].tp += 1
            elif in_expected and not in_regex:
                metrics[cat].fn += 1
            elif not in_expected and in_regex:
                metrics[cat].fp += 1

    return metrics


# ---------------------------------------------------------------------------
# Генерация отчёта
# ---------------------------------------------------------------------------

def generate_report(
    results: list[ComparisonResult],
    metrics: dict[str, CategoryMetrics],
    total_time: float,
) -> str:
    """Сгенерировать текстовый отчёт."""
    lines: list[str] = []
    lines.append("=" * 80)
    lines.append("  SpaCy-АНАЛИЗ КАЧЕСТВА МАСКИРОВАНИЯ PD-PROXY")
    lines.append("=" * 80)
    lines.append("")

    # Сводка
    total = len(results)
    fn_count = sum(1 for r in results if r.false_negatives_regex)
    fp_count = sum(1 for r in results if r.false_positives_regex)
    clean = total - fn_count - fp_count
    lines.append(f"Всего образцов:           {total}")
    lines.append(f"Без ошибок (regex):       {clean}")
    lines.append(f"С пропусками (FN):        {fn_count}")
    lines.append(f"С ложными (FP):           {fp_count}")
    lines.append(f"Время анализа:            {total_time:.1f} с")
    lines.append("")

    # Метрики по категориям
    lines.append("-" * 80)
    lines.append(f"{'Категория':<25} {'TP':>4} {'FP':>4} {'FN':>4}  {'Prec':>6} {'Recall':>6} {'F1':>6}")
    lines.append("-" * 80)

    sorted_cats = sorted(metrics.keys())
    total_tp = total_fp = total_fn = 0
    for cat in sorted_cats:
        m = metrics[cat]
        total_tp += m.tp
        total_fp += m.fp
        total_fn += m.fn
        lines.append(
            f"{cat:<25} {m.tp:>4} {m.fp:>4} {m.fn:>4}  "
            f"{m.precision:>6.1%} {m.recall:>6.1%} {m.f1:>6.1%}"
        )

    # Общие метрики
    overall = CategoryMetrics(tp=total_tp, fp=total_fp, fn=total_fn)
    lines.append("-" * 80)
    lines.append(
        f"{'ИТОГО':<25} {overall.tp:>4} {overall.fp:>4} {overall.fn:>4}  "
        f"{overall.precision:>6.1%} {overall.recall:>6.1%} {overall.f1:>6.1%}"
    )
    lines.append("")

    # SpaCy vs Regex: сравнение скорости
    avg_regex = sum(r.elapsed_regex_ms for r in results) / len(results) if results else 0
    avg_spacy = sum(r.elapsed_spacy_ms for r in results) / len(results) if results else 0
    lines.append(f"Среднее время regex:      {avg_regex:.2f} мс")
    lines.append(f"Среднее время SpaCy:      {avg_spacy:.2f} мс")
    lines.append(f"Regex быстрее в:          {avg_spacy / avg_regex:.1f}x" if avg_regex > 0 else "")
    lines.append("")

    # Детальный анализ: пропуски
    lines.append("=" * 80)
    lines.append("  ДЕТАЛИ: ПРОПУСКИ (False Negatives)")
    lines.append("=" * 80)

    fn_results = [r for r in results if r.false_negatives_regex]
    if fn_results:
        for r in fn_results:
            lines.append(f"\n  📝 {r.sample.description}")
            lines.append(f"     Текст: {r.sample.text[:100]}...")
            lines.append(f"     Пропущены: {', '.join(r.false_negatives_regex)}")

            # Что нашёл SpaCy
            relevant = [e for e in r.spacy_entities if e.pd_category in r.false_negatives_regex]
            if relevant:
                for e in relevant:
                    lines.append(f"     SpaCy нашёл: [{e.label}] \"{e.text}\" → {e.pd_category}")
    else:
        lines.append("  ✅ Пропусков не обнаружено!")
    lines.append("")

    # Детальный анализ: ложные срабатывания
    lines.append("=" * 80)
    lines.append("  ДЕТАЛИ: ЛОЖНЫЕ СРАБАТЫВАНИЯ (False Positives)")
    lines.append("=" * 80)

    fp_results = [r for r in results if r.false_positives_regex]
    if fp_results:
        for r in fp_results:
            lines.append(f"\n  ⚠️  {r.sample.description}")
            lines.append(f"     Текст: {r.sample.text[:100]}")
            lines.append(f"     Ложные: {', '.join(r.false_positives_regex)}")

            # Что regex нашёл лишнего
            for m in r.regex_matches:
                if m.category in r.false_positives_regex:
                    lines.append(f"     Regex лишнее: [{m.category}] \"{m.value}\" (conf={m.confidence:.1f})")

            # SpaCy видит это как...
            for e in r.spacy_entities:
                if e.text in [m.value for m in r.regex_matches if m.category in r.false_positives_regex]:
                    lines.append(f"     SpaCy видит: [{e.label}] \"{e.text}\" → {e.pd_category}")
    else:
        lines.append("  ✅ Ложных срабатываний не обнаружено!")
    lines.append("")

    # SpaCy-only находки (что SpaCy нашёл, но regex не ловит)
    lines.append("=" * 80)
    lines.append("  SpaCy-ONLY НАХОДКИ (не в regex)")
    lines.append("=" * 80)

    for r in results:
        regex_spans = {(m.start, m.end) for m in r.regex_matches}
        spacy_only = [
            e for e in r.spacy_entities
            if not e.pd_category.startswith("_")
            and not any(
                (e.start >= rs and e.end <= re) or (rs >= e.start and re <= e.end)
                for rs, re in regex_spans
            )
        ]
        if spacy_only:
            lines.append(f"\n  📋 {r.sample.description}")
            lines.append(f"     Текст: {r.sample.text[:80]}")
            for e in spacy_only:
                lines.append(f"     SpaCy: [{e.label}] \"{e.text}\" → {e.pd_category}")

    lines.append("")
    lines.append("=" * 80)
    lines.append("  КОНЕЦ ОТЧЁТА")
    lines.append("=" * 80)

    return "\n".join(lines)


def generate_json_report(
    results: list[ComparisonResult],
    metrics: dict[str, CategoryMetrics],
) -> dict[str, Any]:
    """Сгенерировать JSON-отчёт."""
    return {
        "summary": {
            "total_samples": len(results),
            "samples_with_fn": sum(1 for r in results if r.false_negatives_regex),
            "samples_with_fp": sum(1 for r in results if r.false_positives_regex),
            "avg_regex_ms": round(sum(r.elapsed_regex_ms for r in results) / len(results), 2) if results else 0,
            "avg_spacy_ms": round(sum(r.elapsed_spacy_ms for r in results) / len(results), 2) if results else 0,
        },
        "metrics_by_category": {
            cat: {
                "tp": m.tp, "fp": m.fp, "fn": m.fn,
                "precision": round(m.precision, 4),
                "recall": round(m.recall, 4),
                "f1": round(m.f1, 4),
            }
            for cat, m in sorted(metrics.items())
        },
        "false_negatives": [
            {
                "description": r.sample.description,
                "text": r.sample.text[:200],
                "missed_categories": r.false_negatives_regex,
            }
            for r in results if r.false_negatives_regex
        ],
        "false_positives": [
            {
                "description": r.sample.description,
                "text": r.sample.text[:200],
                "extra_categories": r.false_positives_regex,
                "extra_matches": [
                    {"category": m.category, "value": m.value, "confidence": m.confidence}
                    for m in r.regex_matches if m.category in r.false_positives_regex
                ],
            }
            for r in results if r.false_positives_regex
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("🔄 Загрузка SpaCy модели ru_core_news_lg...")
    t0 = time.monotonic()
    nlp = spacy.load("ru_core_news_lg")
    print(f"   ✅ Модель загружена за {time.monotonic() - t0:.1f} с")
    print()

    samples = build_test_samples()
    print(f"📊 Запуск анализа: {len(samples)} тестовых образцов")
    print()

    results: list[ComparisonResult] = []
    start_time = time.monotonic()

    for i, sample in enumerate(samples):
        # Regex
        t1 = time.monotonic()
        regex_matches = detect(sample.text)
        elapsed_regex = (time.monotonic() - t1) * 1000

        # SpaCy
        t2 = time.monotonic()
        spacy_entities = analyze_with_spacy(nlp, sample.text)
        elapsed_spacy = (time.monotonic() - t2) * 1000

        # Сравнение
        result = compare_results(sample, regex_matches, spacy_entities, elapsed_regex, elapsed_spacy)
        results.append(result)

        # Прогресс
        status = "✅" if not result.false_negatives_regex and not result.false_positives_regex else "⚠️"
        print(f"  [{i+1:2d}/{len(samples)}] {status} {sample.description:<45} "
              f"regex:{len(regex_matches):2d} spacy:{len(spacy_entities):2d} "
              f"FN:{len(result.false_negatives_regex)} FP:{len(result.false_positives_regex)}")

    total_time = time.monotonic() - start_time
    print()

    # Метрики
    metrics = compute_metrics(results)

    # Текстовый отчёт
    report_txt = generate_report(results, metrics, total_time)
    report_path = Path(__file__).resolve().parent.parent / "tests" / "spacy-analysis-report.txt"
    report_path.write_text(report_txt, encoding="utf-8")
    print(report_txt)
    print(f"\n📄 Текстовый отчёт: {report_path}")

    # JSON отчёт
    report_json = generate_json_report(results, metrics)
    json_path = Path(__file__).resolve().parent.parent / "tests" / "spacy-analysis-report.json"
    json_path.write_text(json.dumps(report_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📄 JSON отчёт: {json_path}")


if __name__ == "__main__":
    main()
