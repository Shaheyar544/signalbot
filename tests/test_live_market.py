from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from app.monitoring.live_market import LiveMarketSnapshotStore


def test_live_snapshot_replaces_intrabar_candle_and_keeps_live_volume(tmp_path, make_candle):
    store = LiveMarketSnapshotStore(tmp_path / "engine.live.json")
    candle = make_candle(close="101")
    store.update(replace(candle, volume=Decimal("10")))
    store.update(replace(candle, close=Decimal("102"), volume=Decimal("14")))
    payload = store.read()
    assert len(payload["candles"]) == 1
    assert payload["candles"][0]["close"] == "102"
    assert payload["candles"][0]["volume"] == "14"


def test_live_snapshot_keeps_new_candle_for_rollover_and_detects_stale(tmp_path, make_candle):
    store = LiveMarketSnapshotStore(tmp_path / "engine.live.json")
    first = make_candle(offset=0)
    next_candle = make_candle(offset=1)
    store.update(first); store.update(next_candle)
    payload = store.read()
    # The completed candle remains in SQLite; the relay keeps only the current
    # candle for each symbol/timeframe so the dashboard cannot duplicate it.
    assert payload["candles"][0]["open_time"] == next_candle.open_time.isoformat()
    from datetime import datetime, timezone
    assert not store.is_stale(payload)
    assert store.is_stale(payload, datetime.now(timezone.utc) + timedelta(seconds=6))
