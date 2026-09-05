from dataclasses import replace
from decimal import Decimal

from app.strategy.breakout import BreakoutEngine, BreakoutStatus
from app.strategy.retest import RetestEngine
from app.structure.csd import CSDEvent, CSDDirection
from app.structure.swings import SwingPoint, SwingType


def _csd_event(candle, direction=CSDDirection.BULLISH, level="100"):
    swing_type = SwingType.HIGH if direction is CSDDirection.BULLISH else SwingType.LOW
    swing = SwingPoint(candle.symbol, candle.timeframe, candle.open_time, Decimal(level), swing_type, candle)
    return CSDEvent(candle.symbol, candle.timeframe, direction, candle, swing, Decimal("1"))


def test_breakout_then_bullish_retest_close_above_level_is_detected(make_candle):
    breakout_candle = make_candle(offset=0, close="101")
    retest_candle = replace(make_candle(offset=1, close="100.5"), high=Decimal("101"), low=Decimal("99.9"))
    breakouts = BreakoutEngine(retest_zone_percent=Decimal("0.2"))
    retests = RetestEngine(breakouts)

    setup = breakouts.start(_csd_event(breakout_candle))
    event = retests.evaluate(retest_candle)

    assert setup.status is BreakoutStatus.PENDING_RETEST
    assert event is not None and event.status is BreakoutStatus.RETEST_DETECTED
    assert event.breakout_level == Decimal("100")


def test_bullish_retest_is_invalidated_when_closed_below_breakout_level(make_candle):
    breakout_candle = make_candle(offset=0, close="101")
    failure = replace(make_candle(offset=1, close="99.5"), high=Decimal("100.5"), low=Decimal("99"))
    breakouts = BreakoutEngine(retest_zone_percent=Decimal("0.2"))
    breakouts.start(_csd_event(breakout_candle))

    event = RetestEngine(breakouts).evaluate(failure)

    assert event is not None and event.status is BreakoutStatus.INVALIDATED


def test_bearish_retest_and_active_setups_are_pair_isolated(make_candle):
    eth_break = make_candle("ETHUSDT", offset=0, close="99")
    btc_break = make_candle("BTCUSDT", offset=0, close="101")
    btc_retest = replace(make_candle("BTCUSDT", offset=1, close="100.5"), high=Decimal("101"), low=Decimal("99.9"))
    breakouts = BreakoutEngine(retest_zone_percent=Decimal("0.2"))
    breakouts.start(_csd_event(eth_break, CSDDirection.BEARISH))
    breakouts.start(_csd_event(btc_break, CSDDirection.BULLISH))

    event = RetestEngine(breakouts).evaluate(btc_retest)

    assert event is not None and event.symbol == "BTCUSDT"
    assert breakouts.get("ETHUSDT", "15m").status is BreakoutStatus.PENDING_RETEST


def test_pending_setup_expires_after_configured_retest_window(make_candle):
    breakout_candle = make_candle(offset=0, close="101")
    no_retest = make_candle(offset=1, close="103")
    breakouts = BreakoutEngine(retest_zone_percent=Decimal("0.2"), maximum_bars_after_breakout=0)
    breakouts.start(_csd_event(breakout_candle))

    assert RetestEngine(breakouts).evaluate(no_retest) is None
    assert breakouts.get("ETHUSDT", "15m").status is BreakoutStatus.EXPIRED
