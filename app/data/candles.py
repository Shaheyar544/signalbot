from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from bisect import bisect_left, bisect_right, insort

from app.events.models import Candle
from app.storage.repositories import CandleRepository


class CandleStore:
    """Independent, chronologically indexed in-memory candle state for each pair."""
    def __init__(self, repository: CandleRepository | None = None) -> None:
        self._candles: dict[tuple[str, str], dict[datetime, Candle]] = defaultdict(dict)
        self._ordered_keys: dict[tuple[str, str], list[datetime]] = defaultdict(list)
        self._repository = repository

    def add_candle(self, candle: Candle) -> bool:
        """Insert/update a candle. Returns true only when its data changed."""
        bucket = self._candles[(candle.symbol, candle.timeframe)]
        previous = bucket.get(candle.open_time)
        if previous == candle:
            return False
        bucket[candle.open_time] = candle
        if previous is None:
            insort(self._ordered_keys[(candle.symbol, candle.timeframe)], candle.open_time)
        if self._repository is not None:
            self._repository.upsert(candle)
        return True

    def get_latest(self, symbol: str, timeframe: str) -> Candle | None:
        candles = self._candles.get((symbol, timeframe), {})
        keys = self._ordered_keys.get((symbol, timeframe), [])
        return candles[keys[-1]] if keys else None

    def get(self, symbol: str, timeframe: str, open_time: datetime) -> Candle | None:
        return self._candles.get((symbol, timeframe), {}).get(open_time)

    def get_recent(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        candles = self._candles.get((symbol, timeframe), {})
        keys = self._ordered_keys.get((symbol, timeframe), [])
        return [candles[key] for key in keys[-limit:]]

    def get_recent_as_of(self, symbol: str, timeframe: str, limit: int, as_of: datetime) -> list[Candle]:
        """Return only candles known when the decision candle opened."""
        candles = self._candles.get((symbol, timeframe), {})
        keys = self._ordered_keys.get((symbol, timeframe), [])
        end = bisect_right(keys, as_of)
        return [candles[key] for key in keys[max(0, end - limit):end]]

    def get_range(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[Candle]:
        candles = self._candles.get((symbol, timeframe), {})
        keys = self._ordered_keys.get((symbol, timeframe), [])
        begin = bisect_left(keys, start)
        finish = bisect_right(keys, end)
        return [candles[key] for key in keys[begin:finish]]
