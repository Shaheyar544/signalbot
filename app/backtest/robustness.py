"""Parameter sweep helpers that expose plateaus rather than selecting a winner."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Sequence


@dataclass(frozen=True)
class SensitivityPoint:
    parameter: str
    value: Decimal
    expectancy_r: Decimal


@dataclass(frozen=True)
class SensitivityReport:
    parameter: str
    points: tuple[SensitivityPoint, ...]
    plateau_width: int


def sweep(parameter: str, values: Sequence[Decimal], evaluate: Callable[[Decimal], Decimal], *, tolerance: Decimal = Decimal("0.05")) -> SensitivityReport:
    points = tuple(SensitivityPoint(parameter, value, evaluate(value)) for value in values)
    if not points:
        return SensitivityReport(parameter, (), 0)
    best = max(point.expectancy_r for point in points)
    width = sum(abs(point.expectancy_r - best) <= tolerance for point in points)
    return SensitivityReport(parameter, points, width)
