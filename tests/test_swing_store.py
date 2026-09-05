from dataclasses import replace
from decimal import Decimal

import pytest

from app.data.candles import CandleStore
from app.events.models import CandleClosedEvent
from app.indicators.engine import IndicatorEngine
from app.strategy.csd_strategy import CSDStrategyEngine
from app.structure.swing_store import SwingStore
from app.structure.swings import SwingDetector, SwingType


def _with_high(candle, high):
    return replace(candle, high=Decimal(str(high)))


def test_swing_not_visible_before_confirmation(make_candle):
    candles = [_with_high(make_candle(offset=index), high) for index, high in enumerate((102, 103, 107, 103, 102))]
    store = SwingStore(); store.replace(SwingDetector(left_bars=2, right_bars=2).detect(candles))
    pivot = next(swing for swing in store.get_swings(candles[-1].close_time) if swing.kind is SwingType.HIGH)
    assert store.get_swings(candles[2].close_time) == []
    assert store.get_swings(candles[3].close_time) == []
    assert pivot in store.get_swings(candles[4].close_time)


@pytest.mark.asyncio
async def test_replay_engine_has_no_future_access(make_candle):
    def candle(index, high, close):
        source = make_candle(offset=index)
        return replace(source, open=Decimal("1"), high=Decimal(str(high)), low=Decimal("1"), close=Decimal(str(close)))
    series = [candle(index, high, close) for index, (high, close) in enumerate(((1,1),(3,1),(1,1),(2,1),(1,1),(3,3),(3,2.1),(9,9)))]
    signal_candle = series[5]
    async def run(candles):
        store = CandleStore(); seen = []
        engine = CSDStrategyEngine(store, "15m", left_bars=1, right_bars=1, minimum_close_distance_percent=Decimal("0.5"), on_csd=lambda event: seen.append((event.candle.close_time, event.direction, event.broken_swing.candle_open_time)))
        for item in candles:
            store.add_candle(item); await engine.on_candle_closed(CandleClosedEvent(item.symbol, item.timeframe, item))
        return seen
    full_outputs = await run(series)
    truncated_outputs = await run(series[:6])  # delete every candle after the CSD signal bar
    assert truncated_outputs == [item for item in full_outputs if item[0] <= signal_candle.close_time]
    assert truncated_outputs and truncated_outputs[0][0] == signal_candle.close_time


def test_indicator_excludes_forming_candle(make_candle):
    closed = [make_candle(offset=index, closed=True) for index in range(30)]
    forming = make_candle(offset=30, closed=False, close="999999")
    baseline = IndicatorEngine().calculate(closed); with_forming = IndicatorEngine().calculate([*closed, forming])
    assert with_forming.ema == baseline.ema
    assert with_forming.rsi == baseline.rsi
    assert with_forming.macd == baseline.macd
