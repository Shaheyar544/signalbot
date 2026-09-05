from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Sequence

from app.events.models import Candle
from app.structure.market_structure import StructureEvent, StructureKind
from app.structure.swings import SwingPoint, SwingType


class CSDDirection(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


@dataclass(frozen=True)
class CSDEvent:
    symbol: str
    timeframe: str
    direction: CSDDirection
    candle: Candle
    broken_swing: SwingPoint
    close_distance_percent: Decimal


class CSDEngine:
    def __init__(self, minimum_close_distance_percent: Decimal = Decimal("0.05")) -> None:
        if minimum_close_distance_percent < 0:
            raise ValueError("minimum_close_distance_percent cannot be negative")
        self.minimum_close_distance_percent = minimum_close_distance_percent
        self._emitted_breaks: set[tuple[str, str, CSDDirection, object]] = set()

    def evaluate(self, candle: Candle, structure: Sequence[StructureEvent]) -> CSDEvent | None:
        if not candle.is_closed:
            return None
        relevant = [event for event in structure if (event.symbol, event.timeframe) == (candle.symbol, candle.timeframe)]
        bullish = self._latest_swing(relevant, SwingType.HIGH, StructureKind.LH)
        if bullish is not None and candle.close > bullish.price:
            return self._emit(candle, bullish, CSDDirection.BULLISH)
        bearish = self._latest_swing(relevant, SwingType.LOW, StructureKind.HL)
        if bearish is not None and candle.close < bearish.price:
            return self._emit(candle, bearish, CSDDirection.BEARISH)
        return None

    @staticmethod
    def _latest_swing(events: Sequence[StructureEvent], swing_type: SwingType, required_kind: StructureKind) -> SwingPoint | None:
        matches = [event.swing for event in events if event.swing.kind is swing_type and event.kind is required_kind]
        return max(matches, key=lambda swing: swing.candle_open_time) if matches else None

    def _emit(self, candle: Candle, swing: SwingPoint, direction: CSDDirection) -> CSDEvent | None:
        distance = abs(candle.close - swing.price) / swing.price * Decimal(100)
        if distance < self.minimum_close_distance_percent:
            return None
        key = (candle.symbol, candle.timeframe, direction, swing.candle_open_time)
        if key in self._emitted_breaks:
            return None
        self._emitted_breaks.add(key)
        return CSDEvent(candle.symbol, candle.timeframe, direction, candle, swing, distance)
