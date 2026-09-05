"""Reproducible rolling validation windows."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from app.events.models import Candle


@dataclass(frozen=True)
class WalkForwardWindow:
    in_sample_start: datetime
    in_sample_end: datetime
    out_sample_start: datetime
    out_sample_end: datetime


def rolling_windows(start: datetime, end: datetime, *, in_sample_months: int = 6,
                    out_sample_months: int = 2, step_months: int = 2) -> tuple[WalkForwardWindow, ...]:
    windows = []
    cursor = start
    month = timedelta(days=30)
    while cursor + month * (in_sample_months + out_sample_months) <= end:
        in_end = cursor + month * in_sample_months
        out_end = in_end + month * out_sample_months
        windows.append(WalkForwardWindow(cursor, in_end, in_end, out_end))
        cursor += month * step_months
    return tuple(windows)


def split_candles(candles: Sequence[Candle], window: WalkForwardWindow):
    ordered = sorted(candles, key=lambda candle: candle.open_time)
    return (tuple(c for c in ordered if window.in_sample_start <= c.open_time < window.in_sample_end),
            tuple(c for c in ordered if window.out_sample_start <= c.open_time < window.out_sample_end))
