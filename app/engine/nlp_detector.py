"""NLP-обогащение детекции ПДн — Natasha NER (Эшелон 1.5).

Семантический разбор текста с помощью Natasha NER:
- **PER** → новые ``fio``-матчи (если regex не покрыл)
- **LOC** → новые ``address``-матчи (с фильтрацией)
- **ORG** → anti-FP: отклоняем regex fio/address внутри ORG-спана

@business-process Детекция ПДн
@business-rule BR-NLP-1 NLP-обогащение fail-open: при ошибке Natasha pipeline работает без NLP
@business-rule BR-NLP-2 PER-спаны с confidence 0.75 дополняют regex fio-детекцию
@business-rule BR-NLP-3 LOC-спаны с confidence 0.65 дополняют regex address-детекцию (с фильтрацией по адресным маркерам или длине ≥10)
@business-rule BR-NLP-4 ORG-спаны отклоняют regex fio/address-матчи целиком внутри ORG-спана
@integration Natasha NER (natasha==1.6.0, без MorphVocab для Python 3.14)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.engine.detector import PDMatch

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ленивая инициализация Natasha
# ---------------------------------------------------------------------------

_segmenter = None
_ner_tagger = None
_init_done = False


def _ensure_init() -> bool:
    """Инициализировать Natasha (однократно). Возвращает True при успехе."""
    global _segmenter, _ner_tagger, _init_done
    if _init_done:
        return _segmenter is not None
    _init_done = True
    try:
        from natasha import Segmenter, NewsEmbedding, NewsNERTagger
        _segmenter = Segmenter()
        emb = NewsEmbedding()
        _ner_tagger = NewsNERTagger(emb)
        logger.info("Natasha NER инициализирована успешно")
        return True
    except Exception:
        logger.warning("Natasha NER недоступна — NLP-обогащение отключено", exc_info=True)
        _segmenter = None
        _ner_tagger = None
        return False


# ---------------------------------------------------------------------------
# NER-извлечение спанов
# ---------------------------------------------------------------------------

@dataclass
class NERSpan:
    """Спан NER-сущности."""
    type: str    # PER / LOC / ORG
    text: str
    start: int
    stop: int


def extract_ner_spans(text: str) -> list[NERSpan]:
    """Извлечь NER-спаны из текста через Natasha.

    Возвращает пустой список если Natasha не инициализирована.
    """
    if not _ensure_init():
        return []
    try:
        from natasha import Doc
        doc = Doc(text)
        doc.segment(_segmenter)
        doc.tag_ner(_ner_tagger)
        spans = []
        for span in doc.spans:
            spans.append(NERSpan(
                type=span.type,
                text=span.text,
                start=span.start,
                stop=span.stop,
            ))
        return spans
    except Exception:
        logger.warning("Ошибка NER-разбора — пропускаем NLP-этап", exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Адресные маркеры (для фильтрации LOC → address)
# ---------------------------------------------------------------------------

_ADDRESS_MARKERS_RE = re.compile(
    r"(?:ул\.|улица|пр\.|проспект|пер\.|переулок|б-р|бульвар|"
    r"наб\.|набережная|ш\.|шоссе|пл\.|площадь|"
    r"д\.|дом|кв\.|квартира|стр\.|строение|корп\.|корпус|"
    r"г\.|город|обл\.|область|р-н|район|"
    r"пос\.|посёлок|поселок|село|деревня|станица)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# NLP-обогащение pipeline
# ---------------------------------------------------------------------------

def nlp_enrich(
    text: str,
    matches: list[PDMatch],
) -> tuple[list[PDMatch], dict]:
    """Обогатить список матчей NLP-данными (Natasha NER).

    Возвращает ``(обогащённые_матчи, trace_detail)``.

    Args:
        text: Исходный текст.
        matches: Текущий список regex-матчей (после дедупликации).

    Returns:
        Кортеж (новый_список_матчей, dict_с_деталями_для_trace).

    @business-rule BR-NLP-1 fail-open при ошибке
    """
    from app.engine.detector import PDMatch

    detail: dict = {
        "nlp_enabled": True,
        "ner_spans": {"PER": 0, "LOC": 0, "ORG": 0},
        "added_fio": 0,
        "added_address": 0,
        "rejected_by_org": 0,
    }

    ner_spans = extract_ner_spans(text)
    if not ner_spans:
        detail["nlp_enabled"] = bool(_segmenter)
        return matches, detail

    # Считаем спаны по типам
    per_spans = [s for s in ner_spans if s.type == "PER"]
    loc_spans = [s for s in ner_spans if s.type == "LOC"]
    org_spans = [s for s in ner_spans if s.type == "ORG"]
    detail["ner_spans"] = {
        "PER": len(per_spans),
        "LOC": len(loc_spans),
        "ORG": len(org_spans),
    }

    result = list(matches)  # копируем

    # --- 5b: PER → fio (дополнительная детекция) ---
    for span in per_spans:
        # Уже есть regex-матч fio, перекрывающий этот спан?
        has_overlap = any(
            m.category == "fio"
            and m.start <= span.start
            and m.end >= span.stop
            for m in result
        )
        if has_overlap:
            continue
        # Проверяем: может, этот спан вложен в существующий fio-матч
        # (или существующий fio-матч вложен в спан) — считаем перекрытием
        has_any_fio_overlap = any(
            m.category == "fio"
            and m.start < span.stop
            and m.end > span.start
            for m in result
        )
        if has_any_fio_overlap:
            continue
        result.append(PDMatch(
            category="fio",
            value=text[span.start:span.stop],
            start=span.start,
            end=span.stop,
            confidence=0.75,
            rule="Natasha NER: PER",
        ))
        detail["added_fio"] += 1

    # --- 5c: LOC → address (с фильтрацией) ---
    for span in loc_spans:
        has_any_addr_overlap = any(
            m.category == "address"
            and m.start < span.stop
            and m.end > span.start
            for m in result
        )
        if has_any_addr_overlap:
            continue
        loc_text = text[span.start:span.stop]
        # Фильтр: только LOC с адресными маркерами становятся address
        # Топонимы без маркеров (Москва, Санкт-Петербург) — не ПДн
        has_marker = bool(_ADDRESS_MARKERS_RE.search(loc_text))
        if not has_marker:
            continue
        result.append(PDMatch(
            category="address",
            value=loc_text,
            start=span.start,
            end=span.stop,
            confidence=0.65,
            rule="Natasha NER: LOC",
        ))
        detail["added_address"] += 1

    # --- 5d: ORG → anti-FP ---
    rejected_indices = set()
    for span in org_spans:
        for i, m in enumerate(result):
            if m.category not in ("fio", "address"):
                continue
            # Матч целиком внутри ORG-спана?
            if m.start >= span.start and m.end <= span.stop:
                rejected_indices.add(i)
                detail["rejected_by_org"] += 1

    if rejected_indices:
        result = [m for i, m in enumerate(result) if i not in rejected_indices]

    return result, detail
