from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.data.candles import CandleStore
from app.events.models import Candle
from app.storage.database import Database
from app.storage.repositories import CandleRepository


def test_candle_validation(make_candle):
    candle = make_candle()
    assert candle.close == Decimal("101")
    with pytest.raises(ValueError):
        Candle(candle.symbol, candle.timeframe, candle.open_time, candle.close_time, Decimal("100"), Decimal("99"), Decimal("98"), Decimal("101"), Decimal("1"), True)


def test_store_deduplicates_orders_and_retrieves(make_candle):
    store = CandleStore()
    later, first, middle = make_candle(offset=2), make_candle(offset=0), make_candle(offset=1)
    assert store.add_candle(later)
    assert store.add_candle(first)
    assert store.add_candle(middle)
    assert not store.add_candle(middle)
    assert store.get_recent("ETHUSDT", "15m", 3) == [first, middle, later]
    assert store.get_range("ETHUSDT", "15m", first.open_time, middle.open_time) == [first, middle]


def test_multi_pair_state_is_isolated(make_candle):
    store = CandleStore()
    eth, btc = make_candle("ETHUSDT"), make_candle("BTCUSDT", close="99999")
    store.add_candle(eth); store.add_candle(btc)
    assert store.get_latest("ETHUSDT", "15m") == eth
    assert store.get_latest("BTCUSDT", "15m") == btc
    assert store.get_recent("ETHUSDT", "15m", 5) != store.get_recent("BTCUSDT", "15m", 5)


def test_sqlite_unique_candle_persistence(make_candle):
    database = Database(Path(":memory:")); database.open()
    store = CandleStore(CandleRepository(database))
    candle = make_candle()
    store.add_candle(candle); store.add_candle(candle)
    count = database.connection.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
    assert count == 1
    database.close()
