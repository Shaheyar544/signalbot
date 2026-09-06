from __future__ import annotations
from datetime import timedelta

_DURATIONS = {"15m": timedelta(minutes=15), "1h": timedelta(hours=1), "4h": timedelta(hours=4), "1d": timedelta(days=1)}

def duration(timeframe: str) -> timedelta:
    try:
        return _DURATIONS[timeframe]
    except KeyError as error:
        raise ValueError(f"Unknown timeframe: {timeframe!r}") from error
