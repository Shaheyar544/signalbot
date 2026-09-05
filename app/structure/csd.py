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
    close_distance_atr: Decimal | None = None


class CSDEngine:
    def __init__(self, minimum_close_distance_percent: Decimal = Decimal("0.05"), *,
                 breakout_method: str = "percent", minimum_close_atr: Decimal = Decimal("0.15")) -> None:
        if minimum_close_distance_percent < 0 or minimum_close_atr < 0:
            raise ValueError("minimum_close_distance_percent cannot be negative")
        if breakout_method not in {"percent", "atr"}:
            raise ValueError("breakout_method must be 'percent' or 'atr'")
        self.minimum_close_distance_percent = minimum_close_distance_percent
        self.breakout_method = breakout_method
        self.minimum_close_atr = minimum_close_atr
        self._emitted_breaks: set[tuple[str, str, CSDDirection, object]] = set()

    def evaluate(self, candle: Candle, structure: Sequence[StructureEvent], *, atr: Decimal | None = None) -> CSDEvent | None:
        if not candle.is_closed:
            return None
        relevant = [event for event in structure if (event.symbol, event.timeframe) == (candle.symbol, candle.timeframe)]
        bullish = self._latest_swing(relevant, SwingType.HIGH, StructureKind.LH)
        if bullish is not None and candle.close > bullish.price:
            return self._emit(candle, bullish, CSDDirection.BULLISH, atr)
        bearish = self._latest_swing(relevant, SwingType.LOW, StructureKind.HL)
        if bearish is not None and candle.close < bearish.price:
            return self._emit(candle, bearish, CSDDirection.BEARISH, atr)
        return None

    @staticmethod
    def _latest_swing(events: Sequence[StructureEvent], swing_type: SwingType, required_kind: StructureKind) -> SwingPoint | None:
        matches = [event.swing for event in events if event.swing.kind is swing_type and event.kind is required_kind]
        return max(matches, key=lambda swing: swing.candle_open_time) if matches else None

    def _emit(self, candle: Candle, swing: SwingPoint, direction: CSDDirection, atr: Decimal | None) -> CSDEvent | None:
        distance = abs(candle.close - swing.price) / swing.price * Decimal(100)
        distance_atr = abs(candle.close - swing.price) / atr if atr is not None and atr > 0 else None
        if self.breakout_method == "percent" and distance < self.minimum_close_distance_percent:
            return None
        if self.breakout_method == "atr" and (distance_atr is None or distance_atr < self.minimum_close_atr):
            return None
        key = (candle.symbol, candle.timeframe, direction, swing.candle_open_time)
        if key in self._emitted_breaks:
            return None
        self._emitted_breaks.add(key)
        return CSDEvent(candle.symbol, candle.timeframe, direction, candle, swing, distance, distance_atr)
