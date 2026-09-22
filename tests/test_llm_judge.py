"""Тесты LLM-as-a-judge: парсинг ответов и merge-логика."""

import pytest

from app.engine.detector import PDMatch
from app.engine.llm_judge import (
    LLMFinding,
    LLMJudgeResult,
    _parse_verdict,
    merge_results,
)


# ─── _parse_verdict ───────────────────────────────────────────────

class TestParseVerdict:
    def test_clean_json(self):
        """Чистый JSON без fences."""
        raw = '{"findings": [{"text": "Иванов", "category": "fio", "is_pii": true, "confidence": 0.9, "reason": "ФИО"}]}'
        result = _parse_verdict(raw)
        assert len(result) == 1
        assert result[0]["text"] == "Иванов"

    def test_json_with_fences(self):
        """JSON в markdown fences."""
        raw = '```json\n{"findings": [{"text": "test", "category": "email", "is_pii": true, "confidence": 0.8, "reason": "email"}]}\n```'
        result = _parse_verdict(raw)
        assert len(result) == 1
        assert result[0]["category"] == "email"

    def test_json_in_text(self):
        """JSON внутри текста."""
        raw = 'Вот результат анализа: {"findings": [{"text": "123", "category": "inn", "is_pii": true, "confidence": 0.7, "reason": "ИНН"}]} Конец.'
        result = _parse_verdict(raw)
        assert len(result) == 1

    def test_empty_findings(self):
        """Пустой массив findings."""
        raw = '{"findings": []}'
        result = _parse_verdict(raw)
        assert result == []

    def test_invalid_json(self):
        """Невалидный JSON → пустой список."""
        result = _parse_verdict("это не JSON вообще")
        assert result == []

    def test_array_format(self):
        """Массив вместо объекта."""
        raw = '[{"text": "x", "category": "fio", "is_pii": true}]'
        result = _parse_verdict(raw)
        assert len(result) == 1


# ─── merge_results ────────────────────────────────────────────────

def _match(cat: str, val: str, conf: float = 0.8) -> PDMatch:
    return PDMatch(category=cat, value=val, start=0, end=len(val), confidence=conf, rule="regex")


def _finding(text: str, cat: str, is_pii: bool, conf: float = 0.9, reason: str = "") -> LLMFinding:
    return LLMFinding(text=text, category=cat, is_pii=is_pii, confidence=conf, reason=reason)


class TestMergeResults:
    def test_llm_confirms_regex(self):
        """LLM подтверждает regex → confidence обновляется."""
        regex = [_match("fio", "Иванов Иван", 0.7)]
        llm = LLMJudgeResult(
            findings=[_finding("Иванов Иван", "fio", True, 0.95, "ФИО клиента")],
            llm_latency_ms=100,
            raw_response="",
        )
        result = merge_results(regex, llm)
        assert len(result) == 1
        assert result[0].confidence == 0.95  # Обновлён LLM

    def test_llm_rejects_regex(self):
        """LLM отклоняет regex (anti-FP) → совпадение удаляется."""
        regex = [_match("fio", "Пушкин", 0.6)]
        llm = LLMJudgeResult(
            findings=[_finding("Пушкин", "fio", False, 0.99, "Известный поэт, не ПДн")],
            llm_latency_ms=100,
            raw_response="",
        )
        result = merge_results(regex, llm)
        assert len(result) == 0  # Отклонено

    def test_llm_adds_new_finding(self):
        """LLM находит ПДн, пропущенное regex."""
        regex = [_match("phone", "+79161234567")]
        llm = LLMJudgeResult(
            findings=[
                _finding("+79161234567", "phone", True, 0.9),
                _finding("Иванов Иван Петрович", "fio", True, 0.85, "ФИО в свободном тексте"),
            ],
            llm_latency_ms=200,
            raw_response="",
        )
        result = merge_results(regex, llm)
        assert len(result) == 2
        fio = [r for r in result if r.category == "fio"]
        assert len(fio) == 1
        assert fio[0].rule.startswith("LLM-judge")

    def test_llm_error_failopen(self):
        """Ошибка LLM → regex-результат без изменений (fail-open)."""
        regex = [_match("fio", "Иванов"), _match("phone", "+79161234567")]
        llm = LLMJudgeResult(
            findings=[],
            llm_latency_ms=50,
            raw_response="",
            error="Connection timeout",
        )
        result = merge_results(regex, llm)
        assert len(result) == 2  # Без изменений

    def test_llm_empty_findings(self):
        """LLM вернул пустой findings → fail-open."""
        regex = [_match("fio", "Иванов")]
        llm = LLMJudgeResult(findings=[], llm_latency_ms=100, raw_response="")
        result = merge_results(regex, llm)
        assert len(result) == 1  # Без изменений

    def test_llm_low_confidence_ignored(self):
        """LLM finding с confidence < 0.5 не добавляется."""
        regex = []
        llm = LLMJudgeResult(
            findings=[_finding("что-то", "fio", True, 0.3, "сомнительно")],
            llm_latency_ms=100,
            raw_response="",
        )
        result = merge_results(regex, llm)
        assert len(result) == 0

    def test_merge_preserves_sort(self):
        """Результат отсортирован по start."""
        regex = [
            PDMatch("phone", "+79161234567", 50, 62, 0.9, "regex"),
            PDMatch("fio", "Иванов", 0, 6, 0.8, "regex"),
        ]
        llm = LLMJudgeResult(
            findings=[
                _finding("+79161234567", "phone", True, 0.95),
                _finding("Иванов", "fio", True, 0.9),
            ],
            llm_latency_ms=100,
            raw_response="",
        )
        result = merge_results(regex, llm)
        assert result[0].start <= result[1].start

    def test_anti_fp_tolstoy(self):
        """Толстой — писатель, не ПДн."""
        regex = [_match("fio", "Лев Толстой", 0.5)]
        llm = LLMJudgeResult(
            findings=[_finding("Лев Толстой", "fio", False, 0.98, "Известный писатель")],
            llm_latency_ms=100,
            raw_response="",
        )
        result = merge_results(regex, llm)
        assert len(result) == 0

    def test_anti_fp_street_name(self):
        """ул. Пушкина — адрес, не ФИО."""
        regex = [_match("fio", "Пушкина", 0.4)]
        llm = LLMJudgeResult(
            findings=[
                _finding("Пушкина", "fio", False, 0.95, "Часть адреса"),
                _finding("ул. Пушкина, д. 5", "address", True, 0.9, "Адрес"),
            ],
            llm_latency_ms=100,
            raw_response="",
        )
        result = merge_results(regex, llm)
        fio = [r for r in result if r.category == "fio"]
        addr = [r for r in result if r.category == "address"]
        assert len(fio) == 0  # ФИО отклонено
        assert len(addr) == 1  # Адрес добавлен
