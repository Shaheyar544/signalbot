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
    last_closed_candle: dict[tuple[str, str], datetime] = field(default_factory=dict)

    def record_message(self) -> None:
        self.last_message_time = datetime.now(timezone.utc)

    def record_closed_candle(self, candle: Candle) -> None:
        self.last_closed_candle[(candle.symbol, candle.timeframe)] = candle.close_time

    def timeframe_healthy(self, symbol: str, timeframe: str) -> bool:
        return (symbol, timeframe) in self.last_closed_candle
