"""Тесты FastJev-судьи (app.engine.jev_judge).

Все тесты мокают FastJev — реальная модель не загружается.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from app.engine.detector import PDMatch
from app.engine.jev_judge import (
    CATEGORY_DESCRIPTIONS,
    JevBatchResult,
    JevVerdict,
    _make_question,
    reset_jev,
    verify_matches,
)
from app.engine.regex_rules import PDRule

import re


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Сброс singleton перед каждым тестом."""
    reset_jev()
    yield
    reset_jev()


def _make_match(
    category: str = "fio",
    value: str = "Иванов Иван Иванович",
    start: int = 0,
    end: int | None = None,
    confidence: float = 1.0,
) -> PDMatch:
    """Создать тестовый PDMatch."""
    if end is None:
        end = start + len(value)
    rule = PDRule(category=category, pattern=re.compile(r".*"), description="test")
    return PDMatch(
        category=category,
        value=value,
        start=start,
        end=end,
        confidence=confidence,
        rule=rule,
    )


@dataclass
class FakeDecision:
    """Мок Decision из FastJev."""
    id: str
    value: bool
    selected: bool
    probabilities: dict


def _make_fake_decisions(specs: dict[str, tuple[float, float]]) -> dict[str, FakeDecision]:
    """Создать словарь фейковых решений.

    specs: {key: (p_true, p_false)}
    """
    result = {}
    for key, (p_true, p_false) in specs.items():
        result[key] = FakeDecision(
            id=key,
            value=p_true > p_false,
            selected=p_true > p_false,
            probabilities={True: p_true, False: p_false},
        )
    return result


# ---------------------------------------------------------------------------
# Тесты _make_question
# ---------------------------------------------------------------------------


class TestMakeQuestion:
    def test_basic_question(self):
        match = _make_match(category="phone", value="+79001234567", start=10, end=22)
        text = "Позвоните +79001234567 для связи."
        q = _make_question(match, text)
        assert "phone" not in q.instruction  # используется описание, не category
        assert "+79001234567" in q.instruction
        assert "номер телефона" in q.instruction

    def test_context_window(self):
        # Матч далеко от начала — контекст обрезается
        prefix = "A" * 200
        text = prefix + "Иванов Иван" + "B" * 200
        match = _make_match(start=200, end=211)
        q = _make_question(match, text)
        # Контекст в instruction не содержит все 200 A/B
        assert "A" * 100 not in q.instruction
        assert "B" * 100 not in q.instruction


# ---------------------------------------------------------------------------
# Тесты verify_matches — disabled
# ---------------------------------------------------------------------------


class TestVerifyDisabled:
    @patch("app.engine.jev_judge.settings")
    def test_jev_disabled(self, mock_settings):
        mock_settings.jev_enabled = False
        matches = [_make_match()]
        confirmed, batch = verify_matches("test text", matches)
        assert confirmed == matches
        assert batch.total_ms == 0.0

    def test_empty_matches(self):
        confirmed, batch = verify_matches("text", [])
        assert confirmed == []
        assert batch.total_ms == 0.0


# ---------------------------------------------------------------------------
# Тесты verify_matches — fail-open
# ---------------------------------------------------------------------------


class TestVerifyFailOpen:
    @patch("app.engine.jev_judge._get_jev")
    def test_jev_exception_keeps_all_matches(self, mock_get_jev):
        """BR-JEV-01: при ошибке FastJev все матчи сохраняются."""
        mock_get_jev.side_effect = RuntimeError("model crashed")
        matches = [_make_match(), _make_match(category="phone", value="+79001234567")]
        confirmed, batch = verify_matches("Иванов +79001234567", matches)
        assert len(confirmed) == 2
        assert all(v.is_pd for v in batch.verdicts.values())
        assert all(v.error == "jev_error" for v in batch.verdicts.values())


# ---------------------------------------------------------------------------
# Тесты verify_matches — фильтрация
# ---------------------------------------------------------------------------


class TestVerifyFiltering:
    @patch("app.engine.jev_judge._get_jev")
    def test_high_confidence_pd_passes(self, mock_get_jev):
        """Матч с высокой p_true проходит."""
        mock_jev = MagicMock()
        mock_jev.decide_many.return_value = _make_fake_decisions({
            "m0": (0.95, 0.05),
        })
        mock_get_jev.return_value = mock_jev

        matches = [_make_match()]
        confirmed, batch = verify_matches("Иванов Иван Иванович", matches)
        assert len(confirmed) == 1
        assert batch.verdicts["m0"].is_pd is True
        assert batch.verdicts["m0"].probability == pytest.approx(0.95)

    @patch("app.engine.jev_judge._get_jev")
    def test_low_confidence_rejected(self, mock_get_jev):
        """BR-JEV-02: матч с p_false > threshold отклоняется."""
        mock_jev = MagicMock()
        mock_jev.decide_many.return_value = _make_fake_decisions({
            "m0": (0.2, 0.8),  # p_false=0.8 > threshold=0.6
        })
        mock_get_jev.return_value = mock_jev

        matches = [_make_match(value="Александр Пушкин")]
        confirmed, batch = verify_matches("Великий поэт Александр Пушкин", matches)
        assert len(confirmed) == 0
        assert batch.verdicts["m0"].is_pd is False

    @patch("app.engine.jev_judge._get_jev")
    def test_mixed_batch(self, mock_get_jev):
        """Смешанный батч: одни матчи проходят, другие отклоняются."""
        mock_jev = MagicMock()
        mock_jev.decide_many.return_value = _make_fake_decisions({
            "m0": (0.9, 0.1),   # FIO — проходит
            "m1": (0.15, 0.85),  # литературный персонаж — отклоняется
            "m2": (0.95, 0.05),  # паспорт — проходит
        })
        mock_get_jev.return_value = mock_jev

        text = "Иванов 4510 123456 Онегин"
        matches = [
            _make_match(category="fio", value="Иванов", start=0, end=6),
            _make_match(category="fio", value="Онегин", start=20, end=26),
            _make_match(category="passport", value="4510 123456", start=7, end=18),
        ]
        confirmed, batch = verify_matches(text, matches)
        assert len(confirmed) == 2
        categories = [m.category for m in confirmed]
        assert "fio" in categories
        assert "passport" in categories

    @patch("app.engine.jev_judge._get_jev")
    def test_missing_decision_failopen(self, mock_get_jev):
        """Если decide_many не вернул решение для ключа — fail-open."""
        mock_jev = MagicMock()
        mock_jev.decide_many.return_value = {}  # пустой ответ
        mock_get_jev.return_value = mock_jev

        matches = [_make_match()]
        confirmed, batch = verify_matches("Иванов Иван", matches)
        assert len(confirmed) == 1
        assert batch.verdicts["m0"].error == "no_decision"


# ---------------------------------------------------------------------------
# Тесты category_descriptions — полнота
# ---------------------------------------------------------------------------


class TestCategoryDescriptions:
    def test_all_categories_covered(self):
        """Все 21 категория regex-движка имеют описание в JEV."""
        expected = {
            "address", "birth_date", "birth_place", "card_number",
            "cardholder_name", "citizenship", "cvv", "drivers_license",
            "email", "fio", "foreign_passport", "inn", "issue_date",
            "issuing_authority", "military_id", "oms", "passport",
            "phone", "pin", "snils", "subdivision_code",
        }
        assert set(CATEGORY_DESCRIPTIONS.keys()) == expected
