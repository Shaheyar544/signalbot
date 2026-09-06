"""Deterministic checks for historical candle continuity and validity."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from collections import Counter
from decimal import Decimal
from typing import Iterable

from app.events.models import Candle
from app.structure.timeframes import duration


@dataclass(frozen=True)
class IntegrityGap:
    symbol: str
    timeframe: str
    expected_after: datetime
    actual_next: datetime
    missing_candles: int

    @property
    def start(self) -> datetime:
        return self.expected_after

    @property
    def end(self) -> datetime:
        return self.actual_next


@dataclass(frozen=True)
class IntegrityReport:
    symbol: str
    timeframe: str
    candle_count: int
    range_start: datetime | None = None
    range_end: datetime | None = None
    gaps: tuple[IntegrityGap, ...] = ()
    duplicate_open_times: int = 0
    ohlc_violations: int = 0
    empty: bool = False

    @property
    def is_clean(self) -> bool:
        return not (self.empty or self.gaps or self.duplicate_open_times or self.ohlc_violations)

    @property
    def invalid_ohlc(self) -> int:
        return self.ohlc_violations


def check_integrity(symbol: str, timeframe: str, candles: Iterable[Candle]) -> IntegrityReport:
    """Return continuity/duplicate/OHLC diagnostics without mutating input."""
    try:
        expected_delta = duration(timeframe)
    except ValueError as error:
        raise ValueError(f"Unsupported timeframe {timeframe!r}") from error
    ordered = sorted(candles, key=lambda candle: candle.open_time)
    if not ordered:
        return IntegrityReport(symbol, timeframe, 0, empty=True)
    counts = Counter(candle.open_time for candle in ordered)
    duplicate_count = sum(count - 1 for count in counts.values() if count > 1)
    gaps: list[IntegrityGap] = []
    for previous, current in zip(ordered, ordered[1:]):
        expected = previous.open_time + expected_delta
        if current.open_time > expected:
            missing = int((current.open_time - expected) / expected_delta)
            gaps.append(IntegrityGap(symbol, timeframe, expected, current.open_time, missing))
    invalid = 0
    for candle in ordered:
        try:
            if candle.high < max(candle.open, candle.close) or candle.low > min(candle.open, candle.close) or candle.volume < Decimal("0"):
                invalid += 1
        except (AttributeError, TypeError):
            invalid += 1
    return IntegrityReport(symbol, timeframe, len(ordered), ordered[0].open_time, ordered[-1].open_time,
                           tuple(gaps), duplicate_count, invalid)
