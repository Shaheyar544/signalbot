from __future__ import annotations

from typing import Protocol

from app.events.models import CandleClosedEvent


class StrategyEngine(Protocol):
    """Phase 2 will implement this independently for every symbol/timeframe event."""
    async def on_candle_closed(self, event: CandleClosedEvent) -> None: ...
