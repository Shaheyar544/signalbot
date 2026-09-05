import pytest
from dataclasses import replace
from decimal import Decimal
from app.backtest_runner import HistoricalBacktestRunner
from app.backtests import BacktestStatus
from app.config.settings import load_settings
from app.data.candles import CandleStore
from app.storage.database import Database
from app.storage.repositories import BacktestRepository
from app.config.settings import SwingSettings

class SequentialStrategy:
    def __init__(self, store): self.store, self.seen = store, []
    async def on_candle_closed(self, event): self.seen.append(self.store.get_latest(event.symbol, event.timeframe).open_time)

@pytest.mark.asyncio
async def test_runner_processes_stored_candles_sequentially_and_persists_diagnostic_run(make_candle):
    database=Database(__import__('pathlib').Path(':memory:')); database.open(); created=[]
    def factory(store, callback):
        strategy=SequentialStrategy(store); created.append(strategy); return strategy
    runner=HistoricalBacktestRunner(load_settings('tests/fixtures/settings.yaml'), BacktestRepository(database), factory)
    candles=[make_candle(offset=2),make_candle(offset=0),make_candle(offset=1)]
    run=await runner.run(candles)
    assert run.status is BacktestStatus.INCOMPLETE_EXIT_MODEL
    assert created[0].seen == [c.open_time for c in sorted(candles,key=lambda c:c.open_time)]
    assert database.connection.execute('SELECT run_id FROM backtest_runs').fetchone()[0] == run.run_id

@pytest.mark.asyncio
async def test_runner_persists_real_strategy_signal_with_actual_confluence(make_candle):
    database=Database(__import__('pathlib').Path(':memory:')); database.open()
    settings=replace(load_settings('tests/fixtures/settings.yaml'), swing=SwingSettings(1,1))
    candles=[make_candle(offset=index, close='1') for index in range(45)]
    def priced(index, high, close, low='1', open_price='1'):
        candle=make_candle(offset=index, close=str(close)); return replace(candle, open=Decimal(str(open_price)), high=Decimal(str(high)), low=Decimal(str(low)), close=Decimal(str(close)))
    retest=priced(51,3,Decimal('2.1'),Decimal('1.9'),'2')
    candles += [priced(45,1,1), priced(46,3,1), priced(47,1,1), priced(48,2,1), priced(49,1,1), priced(50,3,3), retest]
    run=await HistoricalBacktestRunner(settings, BacktestRepository(database)).run(candles)
    row=database.connection.execute('SELECT setup_valid,confluence_score FROM backtest_trades WHERE run_id=?',(run.run_id,)).fetchone()
    assert row is not None and row[0] == 1 and row[1] >= 1

@pytest.mark.asyncio
async def test_real_strategy_same_candle_collision_persists_sl_first(make_candle):
    database=Database(__import__('pathlib').Path(':memory:')); database.open(); settings=replace(load_settings('tests/fixtures/settings.yaml'), swing=SwingSettings(1,1))
    candles=[make_candle(offset=index, close='1') for index in range(45)]
    def priced(index, high, close, low='1', open_price='1'):
        candle=make_candle(offset=index, close=str(close)); return replace(candle, open=Decimal(str(open_price)), high=Decimal(str(high)), low=Decimal(str(low)), close=Decimal(str(close)))
    candles += [priced(45,1,1),priced(46,3,1),priced(47,1,1),priced(48,2,1),priced(49,1,1),priced(50,3,3),priced(51,3,Decimal('2.1'),'1','2')]
    run=await HistoricalBacktestRunner(settings, BacktestRepository(database)).run(candles)
    assert database.connection.execute('SELECT exit_reason,resolution_method,ambiguous_intrabar FROM backtest_trades WHERE run_id=?',(run.run_id,)).fetchone() == ('SL','SAME_CANDLE',1)
