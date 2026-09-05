"""Reproducible rolling validation windows."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import calendar
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
    while _add_months(cursor, in_sample_months + out_sample_months) <= end:
        in_end = _add_months(cursor, in_sample_months)
        out_end = _add_months(in_end, out_sample_months)
        windows.append(WalkForwardWindow(cursor, in_end, in_end, out_end))
        cursor = _add_months(cursor, step_months)
    return tuple(windows)


def _add_months(value: datetime, months: int) -> datetime:
    month_index = value.year * 12 + value.month - 1 + months
    year, month = divmod(month_index, 12)
    month += 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def split_candles(candles: Sequence[Candle], window: WalkForwardWindow):
    ordered = sorted(candles, key=lambda candle: candle.open_time)
    return (tuple(c for c in ordered if window.in_sample_start <= c.open_time < window.in_sample_end),
            tuple(c for c in ordered if window.out_sample_start <= c.open_time < window.out_sample_end))
