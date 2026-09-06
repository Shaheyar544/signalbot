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
    higher_timeframes: dict[str, bool]
    ema_quality: Decimal = Decimal("0")
    rsi_quality: Decimal = Decimal("0")
    macd_quality: Decimal = Decimal("0")
    volume_quality: Decimal = Decimal("0")
    htf_quality: Decimal = Decimal("0")

class ConfirmationEngine:
    """Evaluates transparent supporting evidence; it never creates an instruction to trade."""
    def __init__(self, volume_ratio_minimum: Decimal = Decimal("1"), rsi_bullish_minimum: Decimal = Decimal("50"),
                 rsi_bearish_maximum: Decimal = Decimal("50"), *,
                 ema_separation_saturation_percent: Decimal = Decimal("0.5"),
                 macd_histogram_saturation_percent: Decimal = Decimal("0.1")) -> None:
        if volume_ratio_minimum < 0 or not (Decimal(0) <= rsi_bullish_minimum <= Decimal(100) and Decimal(0) <= rsi_bearish_maximum <= Decimal(100)):
            raise ValueError("Invalid confirmation threshold")
        self.volume_ratio_minimum = volume_ratio_minimum
        self.rsi_bullish_minimum, self.rsi_bearish_maximum = rsi_bullish_minimum, rsi_bearish_maximum
        self.ema_separation_saturation_percent = ema_separation_saturation_percent
        self.macd_histogram_saturation_percent = macd_histogram_saturation_percent

    def evaluate(self, direction: CSDDirection, primary: IndicatorValues,
                 higher_timeframes: dict[str, IndicatorValues | None]) -> ConfirmationResult:
        ema = self._aligned(direction, primary); rsi = self._rsi_supports(direction, primary.rsi); macd = self._macd_supports(direction, primary)
        volume = primary.volume_ratio is not None and primary.volume_ratio >= self.volume_ratio_minimum
        htf_results = {timeframe: self._not_strongly_opposed(direction, values)
                       for timeframe, values in higher_timeframes.items()}
        agreeing = sum(htf_results.values())
        total = len(htf_results)
        return ConfirmationResult(
            direction=direction,
            ema=ema, rsi=rsi, macd=macd, volume=volume, higher_timeframes=htf_results,
            ema_quality=self._ema_quality(primary) if ema else Decimal(0),
            rsi_quality=abs(primary.rsi - Decimal(50)) / Decimal(50) if rsi and primary.rsi is not None else Decimal(0),
            macd_quality=self._macd_quality(primary) if macd else Decimal(0),
            volume_quality=min((primary.volume_ratio - Decimal(1)) / self.volume_ratio_minimum, Decimal(1)) if volume and primary.volume_ratio is not None and self.volume_ratio_minimum else Decimal(1) if volume else Decimal(0),
            htf_quality=Decimal(agreeing) / Decimal(total) if total else Decimal(0),
        )

    def _ema_quality(self, values: IndicatorValues) -> Decimal:
        slow = values.ema.get(50, Decimal(0))
        if not slow:
            return Decimal(0)
        separation_percent = abs(values.ema.get(10, Decimal(0)) - slow) / slow * Decimal(100)
        return min(separation_percent / self.ema_separation_saturation_percent, Decimal(1))

    def _macd_quality(self, values: IndicatorValues) -> Decimal:
        if values.macd is None:
            return Decimal(0)
        price = values.ema.get(50, Decimal(0))
        if not price:
            return Decimal(0)
        histogram_percent = abs(values.macd.histogram) / price * Decimal(100)
        return min(histogram_percent / self.macd_histogram_saturation_percent, Decimal(1))

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
