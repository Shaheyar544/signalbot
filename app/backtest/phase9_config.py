"""Validation for externally supplied Phase 9 sensitivity dimensions."""
from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


SUPPORTED_SENSITIVITY_DIMENSIONS = (
    "left_bars",
    "right_bars",
    "minimum_close_distance_percent",
    "retest.zone_percent",
    "maximum_bars_after_breakout",
)

_INTEGER_DIMENSIONS = frozenset({"left_bars", "right_bars", "maximum_bars_after_breakout"})
_DECIMAL_DIMENSIONS = frozenset({"minimum_close_distance_percent", "retest.zone_percent"})


def validate_sensitivity_config(payload: Any) -> dict[str, list[Any]]:
    """Validate a project-owner-supplied config without choosing values.

    Required shape::

        {"dimensions": {"left_bars": [ ... ], ...}}

    Values are intentionally preserved exactly; this function only validates
    types, supported names, non-negativity, and duplicate-free lists.
    """
    if not isinstance(payload, dict) or set(payload) != {"dimensions"}:
        raise ValueError("sensitivity config must contain only a 'dimensions' object")
    dimensions = payload["dimensions"]
    if not isinstance(dimensions, dict) or not dimensions:
        raise ValueError("sensitivity dimensions must be a non-empty object")
    unsupported = sorted(set(dimensions) - set(SUPPORTED_SENSITIVITY_DIMENSIONS))
    if unsupported:
        raise ValueError(f"unsupported sensitivity dimension(s): {', '.join(unsupported)}")
    validated: dict[str, list[Any]] = {}
    for name, values in dimensions.items():
        if not isinstance(values, list) or not values:
            raise ValueError(f"sensitivity dimension {name!r} must have a non-empty list")
        if len({str(value) for value in values}) != len(values):
            raise ValueError(f"sensitivity dimension {name!r} contains duplicate values")
        for value in values:
            if name in _INTEGER_DIMENSIONS:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(f"sensitivity dimension {name!r} requires integer values")
                if value < 0 or (name in {"left_bars", "right_bars"} and value < 1):
                    raise ValueError(f"sensitivity dimension {name!r} contains an invalid value")
            elif name in _DECIMAL_DIMENSIONS:
                try:
                    decimal_value = Decimal(str(value))
                except (InvalidOperation, ValueError):
                    raise ValueError(f"sensitivity dimension {name!r} requires decimal values") from None
                if not decimal_value.is_finite() or decimal_value < 0:
                    raise ValueError(f"sensitivity dimension {name!r} contains an invalid value")
        validated[name] = list(values)
    return validated


def load_sensitivity_config(path: str | Path) -> dict[str, list[Any]]:
    """Load and validate the JSON sensitivity contract from *path*."""
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid sensitivity config {source}: {exc}") from exc
    return validate_sensitivity_config(payload)
