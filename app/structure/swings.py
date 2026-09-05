from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Sequence

from app.events.models import Candle
from app.structure.timeframes import duration


class SwingType(StrEnum):
    HIGH = "HIGH"
    LOW = "LOW"


@dataclass(frozen=True)
class SwingPoint:
    symbol: str
    timeframe: str
    candle_open_time: datetime
    price: Decimal
    kind: SwingType
    candle: Candle
    confirmed_time: datetime | None = None


class SwingDetector:
    def __init__(self, left_bars: int = 3, right_bars: int = 3) -> None:
        if left_bars < 1 or right_bars < 1:
            raise ValueError("left_bars and right_bars must both be positive")
        self.left_bars, self.right_bars = left_bars, right_bars

    def detect(self, candles: Sequence[Candle]) -> list[SwingPoint]:
        ordered = sorted((candle for candle in candles if candle.is_closed), key=lambda candle: candle.open_time)
        swings: list[SwingPoint] = []
        for index in range(self.left_bars, len(ordered) - self.right_bars):
            candidate = ordered[index]
            before = ordered[index - self.left_bars:index]
            after = ordered[index + 1:index + self.right_bars + 1]
            if all(candidate.high > candle.high for candle in (*before, *after)):
                swings.append(SwingPoint(candidate.symbol, candidate.timeframe, candidate.open_time, candidate.high, SwingType.HIGH, candidate, candidate.close_time + duration(candidate.timeframe) * self.right_bars))
            if all(candidate.low < candle.low for candle in (*before, *after)):
                swings.append(SwingPoint(candidate.symbol, candidate.timeframe, candidate.open_time, candidate.low, SwingType.LOW, candidate, candidate.close_time + duration(candidate.timeframe) * self.right_bars))
        return swings
