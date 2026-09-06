from dataclasses import replace
from decimal import Decimal

import pytest

from app.data.candles import CandleStore
from app.events.models import CandleClosedEvent
from app.indicators.engine import IndicatorValues, MacdValues
from app.strategy.csd_strategy import CSDStrategyEngine
from app.strategy.breakout import BreakoutStatus
from app.strategy.breakout import BreakoutSetup
from app.strategy.retest import RetestEvent
from app.strategy.regime import MarketRegime
from app.strategy.scoring import SignalClassification
from app.structure.csd import CSDEvent, CSDDirection
from app.structure.swings import SwingPoint, SwingType


def _with_prices(candle, high: int, close: int = 1):
    return replace(candle, open=Decimal("1"), high=Decimal(str(high)), low=Decimal("1"), close=Decimal(str(close)))


@pytest.mark.asyncio
async def test_strategy_engine_emits_csd_only_for_primary_closed_candle(make_candle):
    candles = [_with_prices(make_candle(offset=index), high, close) for index, (high, close) in enumerate(((1, 1), (3, 1), (1, 1), (2, 1), (1, 1), (3, 3)))]
    store = CandleStore()
    for candle in candles:
        store.add_candle(candle)
    observed = []
    engine = CSDStrategyEngine(store, "15m", left_bars=1, right_bars=1, minimum_close_distance_percent=Decimal("0.5"), on_csd=lambda event: observed.append(event))

    await engine.on_candle_closed(CandleClosedEvent("ETHUSDT", "15m", candles[-1]))

    assert len(observed) == 1
    assert observed[0].symbol == "ETHUSDT"


@pytest.mark.asyncio
async def test_strategy_engine_ignores_confirmation_timeframe(make_candle):
    candle = make_candle(timeframe="1h")
    store = CandleStore(); store.add_candle(candle)
    engine = CSDStrategyEngine(store, "15m")

    assert await engine.on_candle_closed(CandleClosedEvent("ETHUSDT", "1h", candle)) is None


@pytest.mark.asyncio
async def test_strategy_engine_starts_and_resolves_retest_lifecycle(make_candle):
    candles = [_with_prices(make_candle(offset=index), high, close) for index, (high, close) in enumerate(((1, 1), (3, 1), (1, 1), (2, 1), (1, 1), (3, 3)))]
    retest_candle = replace(make_candle(offset=6, close="2.1"), open=Decimal("2"), high=Decimal("3"), low=Decimal("1.9"))
    store = CandleStore()
    for candle in [*candles, retest_candle]:
        store.add_candle(candle)
    observed = []
    engine = CSDStrategyEngine(store, "15m", left_bars=1, right_bars=1, minimum_close_distance_percent=Decimal("0.5"), on_retest=lambda event: observed.append(event))

    await engine.on_candle_closed(CandleClosedEvent("ETHUSDT", "15m", candles[-1]))
    await engine.on_candle_closed(CandleClosedEvent("ETHUSDT", "15m", retest_candle))

    assert len(observed) == 1
    assert observed[0].status is BreakoutStatus.RETEST_DETECTED


@pytest.mark.asyncio
async def test_strategy_engine_emits_non_actionable_assessment_after_retest(make_candle):
    candles = [_with_prices(make_candle(offset=index), high, close) for index, (high, close) in enumerate(((1, 1), (3, 1), (1, 1), (2, 1), (1, 1), (3, 3)))]
    retest_candle = replace(make_candle(offset=6, close="2.1"), open=Decimal("2"), high=Decimal("3"), low=Decimal("1.9"))
    store = CandleStore()
    for candle in [*candles, retest_candle]:
        store.add_candle(candle)
    assessments = []
    engine = CSDStrategyEngine(store, "15m", left_bars=1, right_bars=1, minimum_close_distance_percent=Decimal("0.5"), on_assessment=lambda assessment: assessments.append(assessment))

    await engine.on_candle_closed(CandleClosedEvent("ETHUSDT", "15m", candles[-1]))
    await engine.on_candle_closed(CandleClosedEvent("ETHUSDT", "15m", retest_candle))

    assert len(assessments) == 1
    assert assessments[0].score.classification is SignalClassification.WATCH


@pytest.mark.asyncio
async def test_strategy_engine_generates_risk_analysis_only_for_good_or_strong_assessment(make_candle):
    candles = [_with_prices(make_candle(offset=index), high, close) for index, (high, close) in enumerate(((1, 1), (3, 1), (1, 1), (2, 1), (1, 1), (3, 3)))]
    retest_candle = replace(make_candle(offset=6, close="2.1"), open=Decimal("2"), high=Decimal("3"), low=Decimal("1.9"))
    store = CandleStore()
    for candle in [*candles, retest_candle]:
        store.add_candle(candle)
    analyses = []
    engine = CSDStrategyEngine(store, "15m", left_bars=1, right_bars=1, minimum_close_distance_percent=Decimal("0.5"), on_risk_analysis=lambda analysis: analyses.append(analysis))

    await engine.on_candle_closed(CandleClosedEvent("ETHUSDT", "15m", candles[-1]))
    await engine.on_candle_closed(CandleClosedEvent("ETHUSDT", "15m", retest_candle))

    assert analyses == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("entry_mode", "expected_after_breakout", "expected_after_retest"),
    (("retest", [], ["retest"]), ("immediate", ["immediate"], ["immediate"]),
     ("both", ["immediate"], ["immediate", "retest"])),
)
async def test_entry_mode_controls_when_breakout_assessments_are_emitted(
    make_candle, entry_mode, expected_after_breakout, expected_after_retest,
):
    """The public strategy callback distinguishes immediate and retest variants."""
    candles = [_with_prices(make_candle(offset=index), high, close)
               for index, (high, close) in enumerate(((1, 1), (3, 1), (1, 1), (2, 1), (1, 1), (3, 3)))]
    retest_candle = replace(make_candle(offset=6, close="2.1"), open=Decimal("2"), high=Decimal("3"), low=Decimal("1.9"))
    store = CandleStore()
    assessments = []
    engine = CSDStrategyEngine(
        store, "15m", left_bars=1, right_bars=1, minimum_close_distance_percent=Decimal("0.5"),
        entry_mode=entry_mode, on_assessment=lambda assessment: assessments.append(assessment),
    )

    for candle in candles:
        store.add_candle(candle)
    await engine.on_candle_closed(CandleClosedEvent("ETHUSDT", "15m", candles[-1]))
    assert [assessment.entry_mode for assessment in assessments] == expected_after_breakout

    store.add_candle(retest_candle)
    await engine.on_candle_closed(CandleClosedEvent("ETHUSDT", "15m", retest_candle))
    assert [assessment.entry_mode for assessment in assessments] == expected_after_retest


@pytest.mark.asyncio
async def test_strategy_tracks_closed_one_day_indicators_when_configured(make_candle):
    candle = make_candle(timeframe="1d")
    store = CandleStore(); store.add_candle(candle)
    engine = CSDStrategyEngine(store, "15m", confirmation_timeframes=("1h", "4h", "1d"))

    assert await engine.on_candle_closed(CandleClosedEvent("ETHUSDT", "1d", candle)) is None
    assert ("ETHUSDT", "1d") in engine.latest_indicators


@pytest.mark.asyncio
async def test_one_day_confirmation_changes_assessment_score_without_changing_weights(make_candle):
    source = make_candle(offset=0, close="101")
    retest_candle = make_candle(offset=1, close="100.1")
    level = Decimal("100")
    swing = SwingPoint("ETHUSDT", "15m", source.open_time, level, SwingType.HIGH, source)
    csd = CSDEvent("ETHUSDT", "15m", CSDDirection.BULLISH, source, swing, Decimal("0.8"))
    setup = BreakoutSetup("ETHUSDT", "15m", CSDDirection.BULLISH, level, Decimal("99.8"), Decimal("100.2"), csd,
                          BreakoutStatus.RETEST_DETECTED, quality=Decimal("1"))
    retest = RetestEvent("ETHUSDT", "15m", retest_candle, level, BreakoutStatus.RETEST_DETECTED, setup, Decimal("1"))
    aligned = IndicatorValues({10: Decimal("110"), 50: Decimal("100")}, Decimal("55"),
                              MacdValues(Decimal("1"), Decimal("0"), Decimal("1")), volume_ratio=Decimal("2"))
    opposed = IndicatorValues({10: Decimal("90"), 50: Decimal("100")}, Decimal("55"),
                              MacdValues(Decimal("1"), Decimal("0"), Decimal("1")), volume_ratio=Decimal("2"))

    async def assess_with(day_values):
        observed = []
        engine = CSDStrategyEngine(CandleStore(), "15m", confirmation_timeframes=("1h", "4h", "1d"),
                                   on_assessment=observed.append)
        key = ("ETHUSDT", "15m")
        engine.latest_indicators.update({key: aligned, ("ETHUSDT", "1h"): aligned,
                                         ("ETHUSDT", "4h"): aligned, ("ETHUSDT", "1d"): day_values})
        engine.latest_regime[key] = MarketRegime.TRANSITION
        await engine._assess(retest, key, entry_mode="retest")
        return observed[0]

    agreeing = await assess_with(aligned)
    opposing = await assess_with(opposed)

    assert agreeing.confirmation.higher_timeframes["1d"] is True
    assert opposing.confirmation.higher_timeframes["1d"] is False
    assert agreeing.score.total > opposing.score.total
