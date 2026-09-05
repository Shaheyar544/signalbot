from __future__ import annotations
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence
from app.backtests import BacktestRun, BacktestStatus, TradeAudit
from app.config.settings import Settings
from app.data.candles import CandleStore
from app.events.models import Candle, CandleClosedEvent
from app.replay import ClosedCandleConsumer
from app.storage.repositories import BacktestRepository
from app.strategy.csd_strategy import CSDStrategyEngine
from app.strategy.risk import RiskAnalysis
from app.strategy.csd_strategy import SetupAssessment
from app.backtesting import BacktestTradeResolver, TradePlan

StrategyFactory = Callable[[CandleStore, Callable[[RiskAnalysis], object]], ClosedCandleConsumer]

class HistoricalBacktestRunner:
    """Sequential diagnostic replay; it never claims a complete exit model."""
    def __init__(self, settings: Settings, repository: BacktestRepository, strategy_factory: StrategyFactory | None = None) -> None:
        self.settings, self.repository, self.strategy_factory = settings, repository, strategy_factory

    async def run(self, candles: Sequence[Candle]) -> BacktestRun:
        run = BacktestRun(str(uuid.uuid4()), "MULTI_PAIR", self.settings.primary_timeframe, BacktestStatus.INCOMPLETE_EXIT_MODEL, ("Exit allocation, stop movement, trailing, maximum holding period, and end-of-data treatment are not configured.",), datetime.now(timezone.utc))
        self.repository.save_run(run); store = CandleStore(); current: Candle | None = None; assessments: dict[tuple[str, str], SetupAssessment] = {}
        def capture_assessment(assessment: SetupAssessment) -> None:
            assessments[(assessment.retest.symbol, assessment.retest.timeframe)] = assessment
        async def capture(analysis: RiskAnalysis) -> None:
            assert current is not None
            assessment = assessments[(analysis.symbol, analysis.timeframe)]
            plan = TradePlan(analysis.direction, analysis.reference_entry, analysis.stop_loss, analysis.take_profits)
            resolution = BacktestTradeResolver().resolve(plan, low=current.low, high=current.high)
            self.repository.save_trade(TradeAudit(str(uuid.uuid4()), run.run_id, current.close_time, analysis.direction, analysis.reference_entry, analysis.stop_loss, analysis.take_profits[0], analysis.take_profits[1], analysis.take_profits[2], assessment.score.total, assessment.score.classification, current.close_time if resolution.outcome.value != "PENDING" else None, resolution.outcome.value if resolution.outcome.value != "PENDING" else None, None, None, None, resolution.resolution_method.value, resolution.ambiguous_intrabar))
        strategy = self.strategy_factory(store, capture) if self.strategy_factory else CSDStrategyEngine(store, self.settings.primary_timeframe, left_bars=self.settings.swing.left_bars, right_bars=self.settings.swing.right_bars, minimum_close_distance_percent=self.settings.csd.minimum_close_distance_percent, retest_zone_percent=self.settings.retest.zone_percent, maximum_bars_after_breakout=self.settings.retest.maximum_bars_after_breakout, volume_ratio_minimum=self.settings.confirmation.volume_ratio_minimum, rsi_bullish_minimum=self.settings.confirmation.rsi_bullish_minimum, rsi_bearish_maximum=self.settings.confirmation.rsi_bearish_maximum, stop_buffer_percent=self.settings.risk.stop_buffer_percent, scoring_settings=self.settings.scoring, on_assessment=capture_assessment, on_risk_analysis=capture)
        for current in sorted((item for item in candles if item.is_closed), key=lambda item: item.open_time):
            store.add_candle(current); await strategy.on_candle_closed(CandleClosedEvent(current.symbol, current.timeframe, current))
        return run
