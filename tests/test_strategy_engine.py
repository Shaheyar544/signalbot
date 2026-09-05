from dataclasses import replace
from decimal import Decimal

import pytest

from app.data.candles import CandleStore
from app.events.models import CandleClosedEvent
from app.strategy.csd_strategy import CSDStrategyEngine
from app.strategy.breakout import BreakoutStatus
from app.strategy.scoring import SignalClassification


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
    assert assessments[0].score.classification is SignalClassification.CONFIRMATION_PENDING


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

    assert len(analyses) == 1
    assert analyses[0].risk_unit > 0
