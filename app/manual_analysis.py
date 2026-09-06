"""Read-only evaluation of the latest stored closed candle using the live strategy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable

from app.config.settings import Settings
from app.data.candles import CandleStore
from app.events.models import Candle, CandleClosedEvent
from app.strategy.breakout import BreakoutStatus
from app.strategy.csd_strategy import CSDStrategyEngine, SetupAssessment
from app.strategy.regime import RegimeClassifier
from app.strategy.risk import RiskAnalysis


@dataclass(frozen=True)
class ManualAnalysisResult:
    symbol: str
    timeframe: str
    status: str
    analyzed_candle_time: str | None
    classification: str | None = None
    confidence: str | None = None
    direction: str | None = None
    evidence: dict[str, Any] | None = None
    reference_plan: dict[str, str | None] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "status": self.status,
            "read_only": True,
            "analyzed_candle_time": self.analyzed_candle_time,
            "classification": self.classification,
            "confidence": self.confidence,
            "direction": self.direction,
            "evidence": self.evidence,
            "reference_plan": self.reference_plan,
        }


class LatestClosedCandleAnalyzer:
    """Runs the production strategy against an isolated, closed-candle snapshot.

    This class neither writes to SQLite nor dispatches notifications.  It is a
    manual inspection surface, not a second signal generator.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def analyze(self, symbol: str, candles: Iterable[Candle]) -> ManualAnalysisResult:
        closed = [candle for candle in candles if candle.is_closed]
        primary = [candle for candle in closed if candle.timeframe == self.settings.primary_timeframe]
        if not primary:
            return ManualAnalysisResult(symbol, self.settings.primary_timeframe, "NO_CLOSED_CANDLES", None)

        latest_primary = max(primary, key=lambda candle: candle.open_time)
        store = CandleStore()
        strategy = CSDStrategyEngine(
            store,
            self.settings.primary_timeframe,
            left_bars=self.settings.swing.left_bars,
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
            scoring_settings=self.settings.scoring,
            entry_mode=self.settings.variants.entry_mode,
        )
        latest_csd = None
        timeframe_order = {timeframe: index for index, timeframe in enumerate(self.settings.timeframes)}
        for candle in sorted(closed, key=lambda item: (item.close_time, timeframe_order.get(item.timeframe, 99))):
            store.add_candle(candle)
            result = await strategy.on_candle_closed(CandleClosedEvent(candle.symbol, candle.timeframe, candle))
            if candle == latest_primary:
                latest_csd = result

        key = (symbol, self.settings.primary_timeframe)
        assessment = strategy.latest_assessment.get(key)
        if assessment is not None and assessment.retest.candle.open_time == latest_primary.open_time:
            analysis = strategy.latest_risk_analysis.get(key)
            return self._assessment_result(latest_primary, assessment, analysis)

        setup = strategy.breakouts.get(*key)
        if setup is not None and setup.status is BreakoutStatus.PENDING_RETEST:
            return ManualAnalysisResult(
                symbol, self.settings.primary_timeframe, "BREAKOUT_WATCH", latest_primary.close_time.isoformat(),
                direction=str(setup.direction),
                evidence={"breakout": {"status": str(setup.status), "level": str(setup.breakout_level),
                                       "zone_lower": str(setup.zone_lower), "zone_upper": str(setup.zone_upper)}},
            )
        if latest_csd is not None:
            return ManualAnalysisResult(
                symbol, self.settings.primary_timeframe, "CSD_OBSERVED", latest_primary.close_time.isoformat(),
                direction=str(latest_csd.direction),
                evidence={"csd": {"direction": str(latest_csd.direction), "time": latest_csd.candle.close_time.isoformat(),
                                  "close_distance_percent": str(latest_csd.close_distance_percent)}},
            )
        return ManualAnalysisResult(symbol, self.settings.primary_timeframe, "NO_TRADE", latest_primary.close_time.isoformat())

    def _assessment_result(self, candle: Candle, assessment: SetupAssessment, analysis: RiskAnalysis | None) -> ManualAnalysisResult:
        score = assessment.score
        retest = assessment.retest
        evidence: dict[str, Any] = {
            "csd": {"direction": str(retest.setup.source_csd.direction), "time": retest.setup.source_csd.candle.close_time.isoformat(),
                    "close_distance_percent": str(retest.setup.source_csd.close_distance_percent)},
            "breakout": {"status": str(retest.setup.status), "level": str(retest.breakout_level),
                         "zone_lower": str(retest.setup.zone_lower), "zone_upper": str(retest.setup.zone_upper)},
            "retest": {"status": str(retest.status), "time": retest.candle.close_time.isoformat(), "quality": str(retest.quality)},
            "confirmation": {"ema": assessment.confirmation.ema, "rsi": assessment.confirmation.rsi,
                             "macd": assessment.confirmation.macd, "volume": assessment.confirmation.volume,
                             "one_hour": assessment.confirmation.one_hour, "four_hour": assessment.confirmation.four_hour},
            "score": {"total": str(score.total), "components": {name: str(value) for name, value in score.components.items()}},
        }
        plan = None
        if analysis is not None:
            plan = {"entry_low": str(analysis.entry_low), "entry_high": str(analysis.entry_high),
                    "reference_entry": str(analysis.reference_entry), "stop_loss": str(analysis.stop_loss),
                    "take_profit_1": str(analysis.take_profits[0]), "take_profit_2": str(analysis.take_profits[1]),
                    "take_profit_3": str(analysis.take_profits[2]),
                    "take_profit_4": str(analysis.take_profit_4) if analysis.take_profit_4 is not None else None,
                    "risk_unit": str(analysis.risk_unit)}
        return ManualAnalysisResult(
            candle.symbol, candle.timeframe, "QUALIFIED_SIGNAL" if analysis is not None else str(score.classification),
            candle.close_time.isoformat(), str(score.classification), str(score.total), str(retest.setup.direction), evidence, plan,
        )
