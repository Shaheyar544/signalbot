from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from app.events.models import Candle
from app.storage.database import Database
from app.storage.repositories import CandleRepository


def _candles(count=10):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [Candle("ETHUSDT", "15m", start + timedelta(minutes=15 * i), start + timedelta(minutes=15 * i + 14), Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("1"), True) for i in range(count)]


def test_bulk_upsert_round_trips_ordered_range_and_deduplicates():
    database = Database(Path(":memory:")); database.open(); repository = CandleRepository(database)
    candles = _candles(10)
    repository.upsert_many(candles); repository.upsert_many(candles[4:])
    loaded = repository.load_range("ETHUSDT", "15m", candles[2].open_time, candles[8].open_time + timedelta(minutes=15))
    assert [candle.open_time for candle in loaded] == [candle.open_time for candle in candles[2:9]]
    assert database.connection.execute("SELECT count(*) FROM candles").fetchone()[0] == 10


def test_bulk_upsert_uses_one_commit_for_a_large_batch(monkeypatch):
    database = Database(Path(":memory:")); database.open(); repository = CandleRepository(database)
    commits = []
    database.connection.set_trace_callback(lambda statement: commits.append(statement) if statement == "COMMIT" else None)
    repository.upsert_many(_candles(10_000))
    assert len(commits) == 1
