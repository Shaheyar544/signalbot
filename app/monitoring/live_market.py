"""Atomic public intrabar candle snapshots for the read-only dashboard."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from app.events.models import Candle


class LiveMarketSnapshotStore:
    """Shares only public OHLCV updates between the engine and dashboard process."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._candles: dict[tuple[str, str], dict[str, Any]] = {}

    def update(self, candle: Candle) -> None:
        self._candles[(candle.symbol, candle.timeframe)] = {
            "symbol": candle.symbol, "timeframe": candle.timeframe,
            "open_time": candle.open_time.isoformat(), "close_time": candle.close_time.isoformat(),
            "open": str(candle.open), "high": str(candle.high), "low": str(candle.low),
            "close": str(candle.close), "volume": str(candle.volume), "is_closed": candle.is_closed,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"updated_at": datetime.now(timezone.utc).isoformat(), "candles": list(self._candles.values())}
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        temporary_path.replace(self.path)

    def read(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) and isinstance(payload.get("candles"), list) else None

    @staticmethod
    def is_stale(payload: dict[str, Any] | None, now: datetime | None = None, threshold_seconds: float = 5) -> bool:
        if not payload or not payload.get("updated_at"):
            return True
        try:
            updated = datetime.fromisoformat(str(payload["updated_at"]).replace("Z", "+00:00"))
        except ValueError:
            return True
        current = now or datetime.now(timezone.utc)
        return (current - updated).total_seconds() > threshold_seconds
