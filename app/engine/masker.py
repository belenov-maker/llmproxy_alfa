"""Маскирование текста с typed placeholders.

Заменяет обнаруженные ПДн на плейсхолдеры вида [FIO_1], [PASSPORT_1], [PHONE_1].
Возвращает маскированный текст и маппинг для демаскирования.
"""

from __future__ import annotations

import json
from typing import Any

from app.engine.detector import PDMatch


# Маппинг категории → префикс плейсхолдера
_CATEGORY_PREFIX: dict[str, str] = {
    "fio": "FIO",
    "birth_date": "BIRTH_DATE",
    "birth_place": "BIRTH_PLACE",
    "passport": "PASSPORT",
    "citizenship": "CITIZENSHIP",
    "issuing_authority": "ISSUING_AUTH",
    "subdivision_code": "SUBDIV_CODE",
    "issue_date": "ISSUE_DATE",
    "drivers_license": "DRIVERS_LIC",
    "address": "ADDRESS",
    "email": "EMAIL",
    "phone": "PHONE",
    "inn": "INN",
    "card_number": "CARD",
    "cvv": "CVV",
    "pin": "PIN",
    "cardholder_name": "CARDHOLDER",
    "snils": "SNILS",
    "oms": "OMS",
    "foreign_passport": "FPASSPORT",
    "military_id": "MILITARY_ID",
    "secret": "SECRET",
}


# --- Partial masking (частичное) ---

def _partial_mask(value: str, category: str) -> str:
    """Частичное маскирование: показывает начало и конец, скрывает середину.

    Примеры:
        Иванов -> И****в
        +7 (916) 123-45-67 -> +7 (916) ***-**-67
        4510 123456 -> 45** ****56
        test@example.com -> t***@example.com
    """
    if not value:
        return value

    if category == "phone":
        digits = [c for c in value if c.isdigit()]
        if len(digits) >= 7:
            masked_digits = digits[:4] + ["*"] * (len(digits) - 6) + digits[-2:]
            result = list(value)
            di = 0
            for i, c in enumerate(result):
                if c.isdigit():
                    result[i] = masked_digits[di]
                    di += 1
            return "".join(result)

    if category == "email":
        parts = value.split("@")
        if len(parts) == 2:
            local = parts[0]
            if len(local) > 1:
                return local[0] + "*" * (len(local) - 1) + "@" + parts[1]
            return "*@" + parts[1]

    if category == "card_number":
        digits = [c for c in value if c.isdigit()]
        if len(digits) >= 8:
            masked_digits = digits[:4] + ["*"] * (len(digits) - 8) + digits[-4:]
            result = list(value)
            di = 0
            for i, c in enumerate(result):
                if c.isdigit():
                    result[i] = masked_digits[di]
                    di += 1
            return "".join(result)

    if category in ("passport", "foreign_passport", "drivers_license", "military_id"):
        alnums = [(i, c) for i, c in enumerate(value) if c.isdigit()]
        if len(alnums) >= 4:
            masked = list(value)
            for idx, (pos, _) in enumerate(alnums):
                if 2 <= idx < len(alnums) - 2:
                    masked[pos] = "*"
            return "".join(masked)

    if category in ("inn", "snils", "oms", "subdivision_code"):
        digits_pos = [(i, c) for i, c in enumerate(value) if c.isdigit()]
        if len(digits_pos) >= 4:
            masked = list(value)
            for idx, (pos, _) in enumerate(digits_pos):
                if 2 <= idx < len(digits_pos) - 2:
                    masked[pos] = "*"
            return "".join(masked)

    if category in ("cvv", "pin"):
        return "*" * len(value)

    # Общий алгоритм: первый + * + последний
    if len(value) <= 2:
        return "*" * len(value)
    return value[0] + "*" * (len(value) - 2) + value[-1]


class MaskResult:
    """Результат маскирования."""

    __slots__ = ("masked_text", "forward_map", "reverse_map", "pd_count")

    def __init__(
        self,
        masked_text: str,
        forward_map: dict[str, str],
        reverse_map: dict[str, str],
        pd_count: int,
    ) -> None:
        self.masked_text = masked_text
        self.forward_map = forward_map   # original → placeholder
        self.reverse_map = reverse_map   # placeholder → original
        self.pd_count = pd_count


def mask_text(
    text: str,
    matches: list[PDMatch],
    style: str = "placeholder",
) -> MaskResult:
    """Замаскировать текст по результатам детекции.

    Стили:
        - placeholder (default): [FIO_1], [PHONE_1]
        - partial: И****в, +7 (916) ***-**-67

    Args:
        text: Исходный текст.
        matches: Результаты detect().
        style: 'placeholder' или 'partial'.

    Returns:
        MaskResult с маскированным текстом и маппингами.
    """
    if not matches:
        return MaskResult(
            masked_text=text,
            forward_map={},
            reverse_map={},
            pd_count=0,
        )

    # Счётчики для каждой категории
    counters: dict[str, int] = {}
    # Маппинги: value → replacement (для дедупликации)
    forward_map: dict[str, str] = {}
    reverse_map: dict[str, str] = {}

    use_partial = style == "partial"

    # Сортируем по позиции (от конца к началу) чтобы замены не сдвигали индексы
    sorted_matches = sorted(matches, key=lambda m: m.start, reverse=True)

    result = text
    for match in sorted_matches:
        value = match.value
        # Если значение уже встречалось — используем ту же замену
        if value in forward_map:
            replacement = forward_map[value]
        else:
            if use_partial:
                replacement = _partial_mask(value, match.category)
            else:
                prefix = _CATEGORY_PREFIX.get(match.category, match.category.upper())
                counters[match.category] = counters.get(match.category, 0) + 1
                replacement = f"[{prefix}_{counters[match.category]}]"
            forward_map[value] = replacement
            reverse_map[replacement] = value

        result = result[:match.start] + replacement + result[match.end:]

    return MaskResult(
        masked_text=result,
        forward_map=forward_map,
        reverse_map=reverse_map,
        pd_count=len(matches),
    )


def mask_payload(payload: Any, matches: list[PDMatch]) -> tuple[Any, dict[str, str], dict[str, str]]:
    """Рекурсивное маскирование любого payload (str, dict, list).

    Для dict/list — рекурсивно обходит значения.
    Для str — вызывает mask_text.

    Returns:
        (masked_payload, forward_map, reverse_map)
    """
    if isinstance(payload, str):
        result = mask_text(payload, matches)
        return result.masked_text, result.forward_map, result.reverse_map

    if isinstance(payload, dict):
        combined_fwd: dict[str, str] = {}
        combined_rev: dict[str, str] = {}
        masked = {}
        for k, v in payload.items():
            if isinstance(v, str):
                # Фильтруем совпадения для этого значения
                sub_result = mask_text(v, [m for m in matches if m.value in v])
                masked[k] = sub_result.masked_text
                combined_fwd.update(sub_result.forward_map)
                combined_rev.update(sub_result.reverse_map)
            elif isinstance(v, (dict, list)):
                masked_v, fwd, rev = mask_payload(v, matches)
                masked[k] = masked_v
                combined_fwd.update(fwd)
                combined_rev.update(rev)
            else:
                masked[k] = v
        return masked, combined_fwd, combined_rev

    if isinstance(payload, list):
        combined_fwd = {}
        combined_rev = {}
        masked = []
        for item in payload:
            masked_item, fwd, rev = mask_payload(item, matches)
            masked.append(masked_item)
            combined_fwd.update(fwd)
            combined_rev.update(rev)
        return masked, combined_fwd, combined_rev

    return payload, {}, {}
