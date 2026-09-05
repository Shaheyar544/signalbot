from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.events.models import CandleClosedEvent

EventHandler = Callable[[CandleClosedEvent], Awaitable[None] | None]


class EventBus:
    """Small in-process boundary between market data and future strategies."""
    def __init__(self) -> None:
        self._candle_closed_handlers: list[EventHandler] = []

    def subscribe_candle_closed(self, handler: EventHandler) -> None:
        self._candle_closed_handlers.append(handler)

    async def publish_candle_closed(self, event: CandleClosedEvent) -> None:
        for handler in tuple(self._candle_closed_handlers):
            result = handler(event)
            if inspect.isawaitable(result):
                await result
