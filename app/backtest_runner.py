from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from app.backtest.costs import CostModel
from app.backtest.exits import ExitPolicyEngine, SimulatedTrade, TradeState, gross_r
from app.backtests import BacktestRun, BacktestStatus, TradeAudit
from app.config.settings import Settings
from app.data.candles import CandleStore
from app.events.models import Candle, CandleClosedEvent
from app.replay import ClosedCandleConsumer
from app.storage.repositories import BacktestRepository
from app.strategy.csd_strategy import CSDStrategyEngine, SetupAssessment
from app.strategy.regime import RegimeClassifier
from app.strategy.risk import RiskAnalysis

StrategyFactory = Callable[[CandleStore, Callable[[RiskAnalysis], object]], ClosedCandleConsumer]


@dataclass
class _PendingTrade:
    trade: SimulatedTrade
    analysis: RiskAnalysis
    assessment: SetupAssessment
    signal_candle: Candle
    signal_index: int


class HistoricalBacktestRunner:
    """Sequential replay with a post-signal, configuration-driven exit lifecycle."""
    def __init__(self, settings: Settings, repository: BacktestRepository,
                 strategy_factory: StrategyFactory | None = None) -> None:
        self.settings, self.repository, self.strategy_factory = settings, repository, strategy_factory

    async def run(self, candles: Sequence[Candle]) -> BacktestRun:
        run = BacktestRun(str(uuid.uuid4()), "MULTI_PAIR", self.settings.primary_timeframe,
                          BacktestStatus.DIAGNOSTIC,
                          ("Diagnostic replay only: walk-forward and multi-symbol validation remain pending.",),
                          datetime.now(timezone.utc))
        self.repository.save_run(run)
        store = CandleStore()
        assessments: dict[tuple[str, str], SetupAssessment] = {}
        pending: list[_PendingTrade] = []
        current: Candle | None = None
        current_index = -1
        exit_engine = ExitPolicyEngine(self.settings.exit_policy)
        cost_model = CostModel(self.settings.cost)

        def capture_assessment(assessment: SetupAssessment) -> None:
            assessments[(assessment.retest.symbol, assessment.retest.timeframe)] = assessment

        async def capture(analysis: RiskAnalysis) -> None:
            assert current is not None
            assessment = assessments.get((analysis.symbol, analysis.timeframe))
            if assessment is None:
                assessment = getattr(strategy, "latest_assessment", {}).get((analysis.symbol, analysis.timeframe))
            if assessment is None:
                raise RuntimeError("Risk analysis has no matching setup assessment")
            pending.append(_PendingTrade(
                exit_engine.open_trade(direction=analysis.direction, entry_low=analysis.entry_low,
                                       entry_high=analysis.entry_high, reference_entry=analysis.reference_entry,
                                       stop_loss=analysis.stop_loss),
                analysis, assessment, current, current_index,
            ))

        strategy = self.strategy_factory(store, capture) if self.strategy_factory else CSDStrategyEngine(
            store, self.settings.primary_timeframe, left_bars=self.settings.swing.left_bars,
            right_bars=self.settings.swing.right_bars,
            minimum_close_distance_percent=self.settings.csd.minimum_close_distance_percent,
            breakout_method=self.settings.breakout.method,
            minimum_close_atr=self.settings.breakout.minimum_close_atr,
            regime_classifier=RegimeClassifier(**self.settings.regime.__dict__),
            retest_zone_percent=self.settings.retest.zone_percent,
            maximum_bars_after_breakout=self.settings.retest.maximum_bars_after_breakout,
            volume_ratio_minimum=self.settings.confirmation.volume_ratio_minimum,
            rsi_bullish_minimum=self.settings.confirmation.rsi_bullish_minimum,
            rsi_bearish_maximum=self.settings.confirmation.rsi_bearish_maximum,
            stop_buffer_percent=self.settings.risk.stop_buffer_percent,
            scoring_settings=self.settings.scoring, on_assessment=capture_assessment,
            on_risk_analysis=capture,
        )
        ordered = sorted((item for item in candles if item.is_closed), key=lambda item: item.open_time)
        last_candle: dict[tuple[str, str], Candle] = {}
        for current_index, current in enumerate(ordered):
            store.add_candle(current)
            await strategy.on_candle_closed(CandleClosedEvent(current.symbol, current.timeframe, current))
            key = (current.symbol, current.timeframe)
            last_candle[key] = current
            for record in list(pending):
                if record.signal_index >= current_index or (record.analysis.symbol, record.analysis.timeframe) != key:
                    continue
                exit_engine.advance(record.trade, current)
                if record.trade.state is TradeState.CLOSED:
                    self._persist_trade(run, record, cost_model)
                    pending.remove(record)
                elif record.trade.state is TradeState.EXPIRED_UNFILLED:
                    pending.remove(record)
        for record in pending:
            if record.trade.state is TradeState.OPEN:
                exit_engine.close_at_end_of_data(record.trade, last_candle[(record.analysis.symbol, record.analysis.timeframe)])
                self._persist_trade(run, record, cost_model)
        return run

    def _persist_trade(self, run: BacktestRun, record: _PendingTrade, cost_model: CostModel) -> None:
        trade = record.trade
        assert trade.entry_fill_price is not None and trade.entered_at is not None
        assert trade.exit_price is not None and trade.closed_at is not None
        costs = cost_model.breakdown(direction=trade.direction, entry=trade.entry_fill_price,
                                     stop_loss=trade.initial_stop_loss, exit_price=trade.exit_price,
                                     is_stop_exit=trade.exit_reason == "SL", opened_at=trade.entered_at,
                                     closed_at=trade.closed_at)
        targets = record.analysis.take_profits
        gross = gross_r(trade)
        self.repository.save_trade(TradeAudit(
            str(uuid.uuid4()), run.run_id, record.signal_candle.close_time, trade.direction,
            trade.entry_fill_price, trade.initial_stop_loss, targets[0], targets[1], targets[2],
            record.assessment.score.total, record.assessment.score.classification, trade.closed_at,
            trade.exit_reason, gross, costs.total_r, gross - costs.total_r, trade.resolution_method,
            trade.ambiguous_intrabar_events > 0,
            trade.bars_since_entry, trade.mfe_r, trade.mae_r, record.analysis.symbol, record.analysis.regime, None,
        ))
