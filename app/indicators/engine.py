from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from app.events.models import Candle


@dataclass(frozen=True)
class IndicatorValues:
    ema: dict[int, Decimal]
    rsi: Decimal | None = None
    macd: "MacdValues | None" = None
    bollinger: "BollingerBands | None" = None
    volume_sma: Decimal | None = None
    volume_ratio: Decimal | None = None


@dataclass(frozen=True)
class MacdValues:
    line: Decimal
    signal: Decimal
    histogram: Decimal


@dataclass(frozen=True)
class BollingerBands:
    lower: Decimal
    middle: Decimal
    upper: Decimal


class IndicatorEngine:
    """Calculates indicators from chronologically ordered closed candles."""
    def __init__(self, ema_periods: tuple[int, ...] = (10, 50, 200), rsi_period: int = 14,
                 macd_fast: int = 12, macd_slow: int = 26, macd_signal: int = 9,
                 bollinger_period: int = 20, bollinger_stddev: Decimal = Decimal("2"),
                 volume_period: int = 20) -> None:
        periods = (*ema_periods, rsi_period, macd_fast, macd_slow, macd_signal, bollinger_period, volume_period)
        if any(period < 1 for period in periods) or macd_fast >= macd_slow:
            raise ValueError("Indicator periods must be positive and MACD fast must be less than slow")
        self.ema_periods = ema_periods
        self.rsi_period, self.macd_fast, self.macd_slow, self.macd_signal = rsi_period, macd_fast, macd_slow, macd_signal
        self.bollinger_period, self.bollinger_stddev, self.volume_period = bollinger_period, bollinger_stddev, volume_period

    def calculate(self, candles: Sequence[Candle]) -> IndicatorValues:
        closes = [candle.close for candle in candles if candle.is_closed]
        volumes = [candle.volume for candle in candles if candle.is_closed]
        return IndicatorValues(
            ema={period: self._ema(closes, period) for period in self.ema_periods if closes},
            rsi=self._rsi(closes, self.rsi_period),
            macd=self._macd(closes),
            bollinger=self._bollinger(closes),
            volume_sma=self._sma(volumes, self.volume_period),
            volume_ratio=(volumes[-1] / self._sma(volumes, self.volume_period)) if volumes and self._sma(volumes, self.volume_period) not in (None, Decimal(0)) else None,
        )

    @staticmethod
    def _ema(values: list[Decimal], period: int) -> Decimal:
        value = values[0]
        multiplier = Decimal(2) / Decimal(period + 1)
        for current in values[1:]:
            value = (current - value) * multiplier + value
        return value

    @staticmethod
    def _sma(values: list[Decimal], period: int) -> Decimal | None:
        if len(values) < period:
            return None
        window = values[-period:]
        return sum(window) / Decimal(period)

    @staticmethod
    def _rsi(values: list[Decimal], period: int) -> Decimal | None:
        if len(values) <= period:
            return None
        changes = [later - earlier for earlier, later in zip(values, values[1:])]
        gains = [max(change, Decimal(0)) for change in changes]
        losses = [max(-change, Decimal(0)) for change in changes]
        average_gain = sum(gains[:period]) / Decimal(period)
        average_loss = sum(losses[:period]) / Decimal(period)
        for gain, loss in zip(gains[period:], losses[period:]):
            average_gain = (average_gain * Decimal(period - 1) + gain) / Decimal(period)
            average_loss = (average_loss * Decimal(period - 1) + loss) / Decimal(period)
        if average_loss == 0:
            return Decimal(100) if average_gain > 0 else Decimal(50)
        return Decimal(100) - (Decimal(100) / (Decimal(1) + average_gain / average_loss))

    def _macd(self, values: list[Decimal]) -> MacdValues | None:
        if len(values) < self.macd_slow:
            return None
        fast_values = self._ema_series(values, self.macd_fast)
        slow_values = self._ema_series(values, self.macd_slow)
        line_values = [fast - slow for fast, slow in zip(fast_values, slow_values)]
        signal_values = self._ema_series(line_values, self.macd_signal)
        return MacdValues(line_values[-1], signal_values[-1], line_values[-1] - signal_values[-1])

    def _bollinger(self, values: list[Decimal]) -> BollingerBands | None:
        middle = self._sma(values, self.bollinger_period)
        if middle is None:
            return None
        window = values[-self.bollinger_period:]
        deviation = (sum((item - middle) ** 2 for item in window) / Decimal(self.bollinger_period)).sqrt()
        return BollingerBands(middle - self.bollinger_stddev * deviation, middle, middle + self.bollinger_stddev * deviation)

    @staticmethod
    def _ema_series(values: list[Decimal], period: int) -> list[Decimal]:
        current = values[0]
        result = [current]
        multiplier = Decimal(2) / Decimal(period + 1)
        for value in values[1:]:
            current = (value - current) * multiplier + current
            result.append(current)
        return result
