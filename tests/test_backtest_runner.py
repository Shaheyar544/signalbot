from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import sqlite3

import pytest

from app.backtest_runner import HistoricalBacktestRunner
from app.backtests import BacktestStatus
from app.config.settings import load_settings
from app.storage.database import Database
from app.storage.repositories import BacktestRepository
from app.strategy.breakout import BreakoutSetup, BreakoutStatus
from app.strategy.confirmation import ConfirmationResult
from app.strategy.csd_strategy import SetupAssessment
from app.strategy.retest import RetestEvent
from app.strategy.risk import RiskAnalysis
from app.strategy.scoring import ConfidenceScore, SignalClassification
from app.structure.csd import CSDEvent, CSDDirection
from app.structure.swings import SwingPoint, SwingType


def _candle(make_candle, offset, low, high, close):
    return replace(make_candle(offset=offset), open=Decimal(str(close)), low=Decimal(str(low)), high=Decimal(str(high)), close=Decimal(str(close)))


def _analysis_fixture(make_candle):
    source = _candle(make_candle, 0, 98, 102, 100)
    swing = SwingPoint(source.symbol, source.timeframe, source.open_time, Decimal("100"), SwingType.HIGH, source)
    csd = CSDEvent(source.symbol, source.timeframe, CSDDirection.BULLISH, source, swing, Decimal("1"))
    setup = BreakoutSetup(source.symbol, source.timeframe, CSDDirection.BULLISH, Decimal("100"), Decimal("99"), Decimal("101"), csd, BreakoutStatus.RETEST_DETECTED)
    retest = RetestEvent(source.symbol, source.timeframe, source, Decimal("100"), BreakoutStatus.RETEST_DETECTED, setup, Decimal("1"))
    confirmation = ConfirmationResult(CSDDirection.BULLISH, True, True, True, True, {"1h": True, "4h": True},
                                      Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"))
    assessment = SetupAssessment(retest, confirmation, ConfidenceScore(Decimal("10"), {}, SignalClassification.STRONG_SIGNAL))
    analysis = RiskAnalysis(source.symbol, source.timeframe, CSDDirection.BULLISH, Decimal("100"), Decimal("100"), Decimal("100"), Decimal("99"), Decimal("1"), (Decimal("101"), Decimal("102"), Decimal("103")), None)
    return source, assessment, analysis


def test_database_migrates_legacy_fixed_htf_columns_to_agreement_map(tmp_path):
    path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(path)
    legacy.execute("CREATE TABLE backtest_runs (run_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, timeframe TEXT NOT NULL, status TEXT NOT NULL, warnings TEXT NOT NULL, created_at TEXT NOT NULL)")
    legacy.execute("""CREATE TABLE backtest_trades (
        trade_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, signal_time TEXT NOT NULL, direction TEXT NOT NULL,
        entry_price TEXT, stop_loss TEXT, take_profit_1 TEXT, take_profit_2 TEXT, take_profit_3 TEXT,
        score_total TEXT NOT NULL, score_classification TEXT NOT NULL, exit_time TEXT, exit_reason TEXT,
        gross_r TEXT, costs_r TEXT, net_r TEXT, resolution_method TEXT, ambiguous_intrabar INTEGER NOT NULL,
        htf_one_hour INTEGER, htf_four_hour INTEGER)""")
    legacy.execute("INSERT INTO backtest_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("legacy", "run", "2025-01-01T00:00:00+00:00", "BULLISH", None, None, None, None, None,
                    "0", "NO_TRADE", None, None, None, None, None, None, 0, 1, 0))
    legacy.commit(); legacy.close()

    database = Database(path); database.open()
    agreement = database.connection.execute("SELECT htf_agreement FROM backtest_trades WHERE trade_id='legacy'").fetchone()

    assert agreement == ('{"1h": true, "4h": false}',)
    database.close()


class _OneSignalStrategy:
    def __init__(self, assessment, analysis, callback):
        self.latest_assessment = {(analysis.symbol, analysis.timeframe): assessment}
        self.analysis, self.callback, self.emitted = analysis, callback, False

    async def on_candle_closed(self, event):
        if not self.emitted:
            self.emitted = True
            result = self.callback(self.analysis)
            if hasattr(result, "__await__"):
                await result


@pytest.mark.asyncio
async def test_runner_processes_candles_sequentially_and_does_not_use_signal_candle_for_exit(make_candle):
    database = Database(Path(":memory:")); database.open()
    signal, assessment, analysis = _analysis_fixture(make_candle)
    created = []
    def factory(store, callback):
        strategy = _OneSignalStrategy(assessment, analysis, callback); created.append(strategy); return strategy
    candles = [signal, _candle(make_candle, 1, 100, 101, 101), _candle(make_candle, 2, 100.2, 102, 102), _candle(make_candle, 3, 100.2, 103, 103)]
    run = await HistoricalBacktestRunner(load_settings("tests/fixtures/settings.yaml"), BacktestRepository(database), factory).run(candles)
    row = database.connection.execute("SELECT gross_r,costs_r,net_r,exit_reason,resolution_method,entry_time,exit_price,htf_agreement,confirmation_ema,setup_csd FROM backtest_trades WHERE run_id=?", (run.run_id,)).fetchone()
    assert run.status is BacktestStatus.DIAGNOSTIC
    assert row is not None
    assert tuple(Decimal(value) for value in row[:3]) == (Decimal("1.75"), Decimal("0.14"), Decimal("1.61"))
    assert row[3:5] == ("TP3_LAST_LEG", "TP_ONLY")
    assert row[5] is not None and Decimal(row[6]) == Decimal("103")
    assert row[7:] == ('{"1h": true, "4h": true}', 1, 1)
    saved = BacktestRepository(database).list_trades(run.run_id)
    assert saved[0].htf_agreement == {"1h": True, "4h": True}
    assert created[0].emitted


@pytest.mark.asyncio
async def test_runner_persists_same_candle_collision_only_after_the_signal_candle(make_candle):
    database = Database(Path(":memory:")); database.open()
    signal, assessment, analysis = _analysis_fixture(make_candle)
    def factory(store, callback): return _OneSignalStrategy(assessment, analysis, callback)
    run = await HistoricalBacktestRunner(load_settings("tests/fixtures/settings.yaml"), BacktestRepository(database), factory).run([signal, _candle(make_candle, 1, 99, 101, 100)])
    row = database.connection.execute("SELECT gross_r,costs_r,net_r,exit_reason,resolution_method,ambiguous_intrabar FROM backtest_trades WHERE run_id=?", (run.run_id,)).fetchone()
    assert row is not None
    assert tuple(Decimal(value) for value in row[:3]) == (Decimal("-1"), Decimal("0.17"), Decimal("-1.17"))
    assert row[3:] == ("SL", "SAME_CANDLE", 1)


@pytest.mark.asyncio
async def test_runner_persists_the_assessment_entry_mode_with_trade_audit(make_candle):
    database = Database(Path(":memory:")); database.open()
    signal, assessment, analysis = _analysis_fixture(make_candle)
    assessment = replace(assessment, entry_mode="immediate")
    def factory(store, callback): return _OneSignalStrategy(assessment, analysis, callback)

    run = await HistoricalBacktestRunner(load_settings("tests/fixtures/settings.yaml"), BacktestRepository(database), factory).run(
        [signal, _candle(make_candle, 1, 99, 101, 100)],
    )

    assert database.connection.execute(
        "SELECT entry_mode FROM backtest_trades WHERE run_id=?", (run.run_id,),
    ).fetchone() == ("immediate",)


@pytest.mark.asyncio
async def test_runner_excludes_unfilled_entries_from_trade_audits(make_candle):
    database = Database(Path(":memory:")); database.open()
    signal, assessment, analysis = _analysis_fixture(make_candle)
    def factory(store, callback): return _OneSignalStrategy(assessment, analysis, callback)
    candles = [signal, *[_candle(make_candle, offset, 102, 103, 102.5) for offset in range(1, 51)]]
    run = await HistoricalBacktestRunner(load_settings("tests/fixtures/settings.yaml"), BacktestRepository(database), factory).run(candles)
    assert database.connection.execute("SELECT count(*) FROM backtest_trades WHERE run_id=?", (run.run_id,)).fetchone()[0] == 0
