from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from app.data.candles import CandleStore
from app.events.models import Candle, CandleClosedEvent


class ClosedCandleConsumer(Protocol):
    async def on_candle_closed(self, event: CandleClosedEvent) -> object: ...


@dataclass(frozen=True)
class ReplayResult:
    processed_candles: int


class HistoricalReplay:
    """Feeds closed historical candles through the same strategy seam as live data."""
    def __init__(self, store: CandleStore, strategy: ClosedCandleConsumer) -> None:
        self.store = store
        self.strategy = strategy

    async def run(self, candles: Sequence[Candle]) -> ReplayResult:
        processed = 0
        for candle in sorted((item for item in candles if item.is_closed), key=lambda item: item.open_time):
            self.store.add_candle(candle)
            await self.strategy.on_candle_closed(CandleClosedEvent(candle.symbol, candle.timeframe, candle))
            processed += 1
        return ReplayResult(processed)
