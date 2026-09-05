"""Causal, deterministic market-regime classification.

The classifier is intentionally observational by default.  It attaches context
to a signal and replay audit; it does not filter or alter V1 signal generation
unless a future explicitly configured variant consumes it.
"""
from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from app.indicators.engine import IndicatorValues


class MarketRegime(StrEnum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    TRANSITION = "TRANSITION"


class RegimeClassifier:
    """Classify one closed candle from causal EMA/ATR inputs only."""
    def __init__(self, *, high_atr_percent: Decimal = Decimal("1.5"),
                 low_atr_percent: Decimal = Decimal("0.3"),
                 trend_ema_separation_percent: Decimal = Decimal("0.2"),
                 range_ema_separation_percent: Decimal = Decimal("0.05")) -> None:
        if min(high_atr_percent, low_atr_percent, trend_ema_separation_percent, range_ema_separation_percent) < 0:
            raise ValueError("regime thresholds cannot be negative")
        if low_atr_percent > high_atr_percent:
            raise ValueError("low_atr_percent cannot exceed high_atr_percent")
        if range_ema_separation_percent > trend_ema_separation_percent:
            raise ValueError("range EMA separation cannot exceed trend separation")
        self.high_atr_percent = high_atr_percent
        self.low_atr_percent = low_atr_percent
        self.trend_ema_separation_percent = trend_ema_separation_percent
        self.range_ema_separation_percent = range_ema_separation_percent

    def classify(self, close: Decimal, indicators: IndicatorValues) -> MarketRegime:
        if close <= 0:
            raise ValueError("regime classification requires a positive close")
        atr_percent = indicators.atr / close * Decimal(100) if indicators.atr is not None else None
        if atr_percent is not None and atr_percent >= self.high_atr_percent:
            return MarketRegime.HIGH_VOLATILITY
        if atr_percent is not None and atr_percent <= self.low_atr_percent:
            return MarketRegime.LOW_VOLATILITY
        ema10 = indicators.ema.get(10)
        ema50 = indicators.ema.get(50)
        if ema10 is None or ema50 is None or ema50 == 0:
            return MarketRegime.TRANSITION
        separation = abs(ema10 - ema50) / ema50 * Decimal(100)
        if separation >= self.trend_ema_separation_percent:
            return MarketRegime.TREND_UP if ema10 > ema50 and close >= ema50 else MarketRegime.TREND_DOWN if ema10 < ema50 and close <= ema50 else MarketRegime.TRANSITION
        if separation <= self.range_ema_separation_percent:
            return MarketRegime.RANGE
        return MarketRegime.TRANSITION
