from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.events.models import Candle


@dataclass
class HealthStatus:
    running: bool = False
    websocket_connected: bool = False
    database_connected: bool = False
    enabled_symbols: int = 0
    last_message_time: datetime | None = None
    first_message_time: datetime | None = None
    active_subscriptions: tuple[str, ...] = ()
    subscription_acknowledged: bool = False
    messages_by_stream: dict[tuple[str, str], int] = field(default_factory=dict)
    reconnect_attempts: int = 0
    last_reconnect_error: str | None = None
    last_closed_candle: dict[tuple[str, str], datetime] = field(default_factory=dict)

    def record_message(self, candle: Candle) -> None:
        now = datetime.now(timezone.utc)
        self.last_message_time = now
        self.first_message_time = self.first_message_time or now
        key = (candle.symbol, candle.timeframe)
        self.messages_by_stream[key] = self.messages_by_stream.get(key, 0) + 1

    def record_closed_candle(self, candle: Candle) -> None:
        self.last_closed_candle[(candle.symbol, candle.timeframe)] = candle.close_time

    def timeframe_healthy(self, symbol: str, timeframe: str) -> bool:
        return (symbol, timeframe) in self.last_closed_candle
