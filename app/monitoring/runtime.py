"""Atomic, local persistence for the engine's read-only health snapshot."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.monitoring.health import HealthStatus


class RuntimeHealthSnapshotStore:
    """Publishes health state for a separate local monitoring process."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def write(self, health: HealthStatus) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "running": health.running,
            "websocket_connected": health.websocket_connected,
            "database_connected": health.database_connected,
            "enabled_symbol_count": health.enabled_symbols,
            "last_message_time": health.last_message_time.isoformat() if health.last_message_time else None,
            "first_message_time": health.first_message_time.isoformat() if health.first_message_time else None,
            "active_subscriptions": list(health.active_subscriptions),
            "subscription_acknowledged": health.subscription_acknowledged,
            "messages_by_stream": [
                {"symbol": symbol, "timeframe": timeframe, "count": count}
                for (symbol, timeframe), count in sorted(health.messages_by_stream.items())
            ],
            "reconnect_attempts": health.reconnect_attempts,
            "last_reconnect_error": health.last_reconnect_error,
            "last_closed_candles": [
                {"symbol": symbol, "timeframe": timeframe, "close_time": close_time.isoformat()}
                for (symbol, timeframe), close_time in sorted(health.last_closed_candle.items())
            ],
        }
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        temporary_path.replace(self.path)

    def read(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return payload
