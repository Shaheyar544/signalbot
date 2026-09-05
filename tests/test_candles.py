from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.data.candles import CandleStore
from app.events.models import Candle
from app.storage.database import Database
from app.storage.repositories import CandleRepository
from app.events.models import CandleClosedEvent
from app.strategy.csd_strategy import CSDStrategyEngine
from app.backtest_runner import HistoricalBacktestRunner
from app.config.settings import load_settings
from app.storage.database import Database
from app.storage.repositories import BacktestRepository
from tests.test_backtest_runner import _analysis_fixture, _OneSignalStrategy, _candle


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


class _ReferenceCandleStore(CandleStore):
    """Pre-optimization access behavior used only as an equivalence oracle."""
    def get_recent_as_of(self, symbol, timeframe, limit, as_of):
        candles = self._candles.get((symbol, timeframe), {})
        keys = [key for key in sorted(candles) if key <= as_of]
        return [candles[key] for key in keys[-limit:]]


async def _strategy_trace(store, candles):
    trace = {"csd": [], "assessments": [], "risk": []}
    engine = CSDStrategyEngine(store, "15m", left_bars=1, right_bars=1,
                               minimum_close_distance_percent=Decimal("0.5"),
                               on_csd=trace["csd"].append,
                               on_assessment=trace["assessments"].append,
                               on_risk_analysis=trace["risk"].append)
    for candle in candles:
        store.add_candle(candle)
        await engine.on_candle_closed(CandleClosedEvent(candle.symbol, candle.timeframe, candle))
    return trace


@pytest.mark.asyncio
async def test_optimized_store_is_strategy_equivalent_to_reference_access(make_candle):
    candles = []
    for index, (high, close) in enumerate(((1, 1), (3, 1), (1, 1), (2, 1), (1, 1), (3, 3))):
        candle = make_candle(offset=index)
        candles.append(Candle(candle.symbol, candle.timeframe, candle.open_time, candle.close_time,
                              Decimal("1"), Decimal(str(high)), Decimal("1"), Decimal(str(close)), candle.volume, True))
    trace_reference = await _strategy_trace(_ReferenceCandleStore(), candles)
    trace_optimized = await _strategy_trace(CandleStore(), candles)
    assert trace_optimized == trace_reference


@pytest.mark.asyncio
async def test_replay_trade_audit_is_equivalent_to_reference_store(make_candle):
    signal, assessment, analysis = _analysis_fixture(make_candle)
    candles = [signal, _candle(make_candle, 1, 100, 101, 101),
                _candle(make_candle, 2, 100, 102, 102)]

    async def run(reference: bool, path):
        database = Database(path); database.open()
        original = CandleStore.get_recent_as_of
        if reference:
            CandleStore.get_recent_as_of = _ReferenceCandleStore.get_recent_as_of
        try:
            def factory(store, callback):
                return _OneSignalStrategy(assessment, analysis, callback)
            result = await HistoricalBacktestRunner(load_settings("tests/fixtures/settings.yaml"), BacktestRepository(database), factory).run(candles)
            rows = database.connection.execute("SELECT signal_time,direction,entry_price,stop_loss,take_profit_1,take_profit_2,take_profit_3,gross_r,costs_r,net_r,exit_reason,resolution_method,ambiguous_intrabar FROM backtest_trades WHERE run_id=?", (result.run_id,)).fetchall()
            database.close()
            return rows
        finally:
            CandleStore.get_recent_as_of = original

    assert await run(False, Path(":memory:")) == await run(True, Path(":memory:"))
