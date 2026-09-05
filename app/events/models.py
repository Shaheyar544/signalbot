from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def utc_from_millis(value: int | str) -> datetime:
    return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)


@dataclass(frozen=True)
class Candle:
    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    is_closed: bool

    def __post_init__(self) -> None:
        if self.open_time.tzinfo is None or self.close_time.tzinfo is None:
            raise ValueError("Candle timestamps must be timezone-aware")
        if self.close_time < self.open_time:
            raise ValueError("Candle close_time cannot precede open_time")
        try:
            values = (self.open, self.high, self.low, self.close, self.volume)
            if any(not isinstance(value, Decimal) for value in values):
                raise TypeError("Candle prices and volume must be Decimal")
        except InvalidOperation as error:
            raise ValueError("Invalid candle decimal") from error
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("Candle OHLC values are inconsistent")
        if self.volume < 0:
            raise ValueError("Candle volume cannot be negative")

    @property
    def key(self) -> tuple[str, str, datetime]:
        return (self.symbol, self.timeframe, self.open_time)


@dataclass(frozen=True)
class CandleClosedEvent:
    symbol: str
    timeframe: str
    candle: Candle
