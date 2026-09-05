from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.indicators.engine import IndicatorValues
from app.structure.csd import CSDDirection


@dataclass(frozen=True)
class ConfirmationResult:
    direction: CSDDirection
    ema: bool
    rsi: bool
    macd: bool
    volume: bool
    one_hour: bool
    four_hour: bool


class ConfirmationEngine:
    """Evaluates transparent supporting evidence; it never creates an instruction to trade."""
    def __init__(self, volume_ratio_minimum: Decimal = Decimal("1"), rsi_bullish_minimum: Decimal = Decimal("50"),
                 rsi_bearish_maximum: Decimal = Decimal("50")) -> None:
        if volume_ratio_minimum < 0 or not (Decimal(0) <= rsi_bullish_minimum <= Decimal(100) and Decimal(0) <= rsi_bearish_maximum <= Decimal(100)):
            raise ValueError("Invalid confirmation threshold")
        self.volume_ratio_minimum = volume_ratio_minimum
        self.rsi_bullish_minimum, self.rsi_bearish_maximum = rsi_bullish_minimum, rsi_bearish_maximum

    def evaluate(self, direction: CSDDirection, primary: IndicatorValues,
                 one_hour: IndicatorValues | None, four_hour: IndicatorValues | None) -> ConfirmationResult:
        return ConfirmationResult(
            direction=direction,
            ema=self._aligned(direction, primary),
            rsi=self._rsi_supports(direction, primary.rsi),
            macd=self._macd_supports(direction, primary),
            volume=primary.volume_ratio is not None and primary.volume_ratio >= self.volume_ratio_minimum,
            one_hour=self._not_strongly_opposed(direction, one_hour),
            four_hour=self._not_strongly_opposed(direction, four_hour),
        )

    @staticmethod
    def _aligned(direction: CSDDirection, values: IndicatorValues | None) -> bool:
        if values is None or 10 not in values.ema or 50 not in values.ema:
            return False
        return values.ema[10] > values.ema[50] if direction is CSDDirection.BULLISH else values.ema[10] < values.ema[50]

    def _rsi_supports(self, direction: CSDDirection, rsi: Decimal | None) -> bool:
        if rsi is None:
            return False
        return rsi >= self.rsi_bullish_minimum if direction is CSDDirection.BULLISH else rsi <= self.rsi_bearish_maximum

    @staticmethod
    def _macd_supports(direction: CSDDirection, values: IndicatorValues) -> bool:
        if values.macd is None:
            return False
        return values.macd.histogram >= 0 if direction is CSDDirection.BULLISH else values.macd.histogram <= 0

    def _not_strongly_opposed(self, direction: CSDDirection, values: IndicatorValues | None) -> bool:
        if values is None or 10 not in values.ema or 50 not in values.ema:
            return False
        return values.ema[10] >= values.ema[50] if direction is CSDDirection.BULLISH else values.ema[10] <= values.ema[50]
