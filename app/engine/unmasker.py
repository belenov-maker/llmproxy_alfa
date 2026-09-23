"""Демаскирование текста по обратному маппингу.

Заменяет плейсхолдеры [FIO_1], [PASSPORT_1] и т.д. обратно на оригинальные значения.
"""

from __future__ import annotations

import re
from typing import Any

# Паттерн для поиска плейсхолдеров вида [CATEGORY_N]
_PLACEHOLDER_RE = re.compile(r"\[[A-Z_]+_\d+\]")

# Паттерн для typed-масок вида [ФИО:И. И. И.] или [EMAIL:t***@***.com]
_TYPED_RE = re.compile(r"\[[\wА-Яа-яЁё_]+:[^\]]+\]")

# Объединённый паттерн: сначала typed (более сложный), потом placeholder
_COMBINED_RE = re.compile(
    r"\[[\wА-Яа-яЁё_]+:[^\]]+\]"
    r"|"
    r"\[[A-Z_]+_\d+\]"
)


def unmask_text(text: str, reverse_map: dict[str, str]) -> str:
    """Демаскировать текст, заменяя плейсхолдеры на оригинальные значения.

    Поддерживает два формата:
        - placeholder: [FIO_1], [PHONE_1]
        - typed: [ФИО:И. И. И.], [ТЕЛ:+7 *** ***-**-67]

    Args:
        text: Маскированный текст.
        reverse_map: Маппинг placeholder → original.

    Returns:
        Демаскированный текст.
    """
    if not reverse_map:
        return text

    def _replace(m: re.Match) -> str:
        placeholder = m.group(0)
        return reverse_map.get(placeholder, placeholder)

    return _COMBINED_RE.sub(_replace, text)


def unmask_payload(payload: Any, reverse_map: dict[str, str]) -> Any:
    """Рекурсивное демаскирование любого payload (str, dict, list).

    Args:
        payload: Маскированный payload.
        reverse_map: Маппинг placeholder → original.

    Returns:
        Демаскированный payload.
    """
    if isinstance(payload, str):
        return unmask_text(payload, reverse_map)

    if isinstance(payload, dict):
        return {k: unmask_payload(v, reverse_map) for k, v in payload.items()}

    if isinstance(payload, list):
        return [unmask_payload(item, reverse_map) for item in payload]

    return payload
