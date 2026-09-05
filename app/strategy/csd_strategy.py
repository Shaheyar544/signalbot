from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from decimal import Decimal

from app.data.candles import CandleStore
from app.events.models import CandleClosedEvent
from app.indicators.engine import IndicatorEngine, IndicatorValues
from app.strategy.breakout import BreakoutEngine
from app.strategy.breakout import BreakoutStatus
from app.strategy.confirmation import ConfirmationEngine, ConfirmationResult
from app.strategy.retest import RetestEngine, RetestEvent
from app.strategy.risk import RiskAnalysis, RiskEngine
from app.strategy.scoring import ConfidenceScore, ScoringEngine, SignalClassification
from app.structure.csd import CSDEngine, CSDEvent
from app.structure.market_structure import MarketStructureEngine, StructureEvent
from app.structure.swings import SwingDetector

LOGGER = logging.getLogger(__name__)
CSDHandler = Callable[[CSDEvent], Awaitable[None] | None]
RetestHandler = Callable[[RetestEvent], Awaitable[None] | None]


@dataclass(frozen=True)
class SetupAssessment:
    retest: RetestEvent
    confirmation: ConfirmationResult
    score: ConfidenceScore


AssessmentHandler = Callable[[SetupAssessment], Awaitable[None] | None]
RiskHandler = Callable[[RiskAnalysis], Awaitable[None] | None]


class CSDStrategyEngine:
    """Phase 2 composition root; it emits analysis events, never trade instructions."""
    def __init__(self, store: CandleStore, primary_timeframe: str, *, left_bars: int = 3,
                 right_bars: int = 3, minimum_close_distance_percent: Decimal = Decimal("0.05"),
                 retest_zone_percent: Decimal = Decimal("0.20"), on_csd: CSDHandler | None = None,
                 on_retest: RetestHandler | None = None, maximum_bars_after_breakout: int = 12,
                 on_assessment: AssessmentHandler | None = None, volume_ratio_minimum: Decimal = Decimal("1"),
                 rsi_bullish_minimum: Decimal = Decimal("50"), rsi_bearish_maximum: Decimal = Decimal("50"),
                 stop_buffer_percent: Decimal = Decimal("0"), on_risk_analysis: RiskHandler | None = None) -> None:
        self.store = store
        self.primary_timeframe = primary_timeframe
        self.indicators = IndicatorEngine()
        self.swings = SwingDetector(left_bars, right_bars)
        self.structure = MarketStructureEngine()
        self.csd = CSDEngine(minimum_close_distance_percent)
        self.breakouts = BreakoutEngine(retest_zone_percent, maximum_bars_after_breakout)
        self.retests = RetestEngine(self.breakouts)
        self.confirmation = ConfirmationEngine(volume_ratio_minimum, rsi_bullish_minimum, rsi_bearish_maximum)
        self.scoring = ScoringEngine()
        self.risk = RiskEngine(stop_buffer_percent)
        self.on_csd = on_csd
        self.on_retest = on_retest
        self.on_assessment = on_assessment
        self.on_risk_analysis = on_risk_analysis
        self.latest_indicators: dict[tuple[str, str], IndicatorValues] = {}
        self.latest_structure: dict[tuple[str, str], list[StructureEvent]] = {}
        self.latest_assessment: dict[tuple[str, str], SetupAssessment] = {}
        self.latest_risk_analysis: dict[tuple[str, str], RiskAnalysis] = {}

    async def on_candle_closed(self, event: CandleClosedEvent) -> CSDEvent | None:
        candles = self.store.get_recent_as_of(event.symbol, event.timeframe, 500, event.candle.open_time)
        key = (event.symbol, event.timeframe)
        self.latest_indicators[key] = self.indicators.calculate(candles)
        if event.timeframe != self.primary_timeframe:
            return None
        retest_event = self.retests.evaluate(event.candle)
        if retest_event is not None:
            LOGGER.info("%s %s", retest_event.symbol, retest_event.status)
            if self.on_retest is not None:
                result = self.on_retest(retest_event)
                if inspect.isawaitable(result):
                    await result
            if retest_event.status is BreakoutStatus.RETEST_DETECTED:
                confirmation = self.confirmation.evaluate(
                    retest_event.setup.direction,
                    self.latest_indicators[key],
                    self.latest_indicators.get((event.symbol, "1h")),
                    self.latest_indicators.get((event.symbol, "4h")),
                )
                assessment = SetupAssessment(retest_event, confirmation, self.scoring.score(confirmation, has_csd=True, has_breakout=True, has_retest=True))
                self.latest_assessment[key] = assessment
                if self.on_assessment is not None:
                    result = self.on_assessment(assessment)
                    if inspect.isawaitable(result):
                        await result
                if assessment.score.classification is SignalClassification.CONFIRMATION_PENDING:
                    analysis = self.risk.calculate(assessment, self.latest_structure.get(key, []))
                    self.latest_risk_analysis[key] = analysis
                    if self.on_risk_analysis is not None:
                        result = self.on_risk_analysis(analysis)
                        if inspect.isawaitable(result):
                            await result
        structure = self.structure.evaluate(event.symbol, event.timeframe, self.swings.detect(candles))
        self.latest_structure[key] = structure
        csd_event = self.csd.evaluate(event.candle, structure)
        if csd_event is not None:
            LOGGER.info("%s %s CSD detected at %s", csd_event.symbol, csd_event.direction, csd_event.candle.close_time.isoformat())
            self.breakouts.start(csd_event)
            if self.on_csd is not None:
                result = self.on_csd(csd_event)
                if inspect.isawaitable(result):
                    await result
        return csd_event
