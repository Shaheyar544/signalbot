from decimal import Decimal

from app.backtesting import BacktestTradeResolver, ResolutionMethod, TradeOutcome, TradePlan
from app.structure.csd import CSDDirection


def plan(direction=CSDDirection.BULLISH):
    return TradePlan(direction, Decimal("100"), Decimal("95"), (Decimal("105"), Decimal("110"), Decimal("115"))) if direction is CSDDirection.BULLISH else TradePlan(direction, Decimal("100"), Decimal("105"), (Decimal("95"), Decimal("90"), Decimal("85")))


def test_long_sl_only_and_tp_only_are_resolved():
    resolver = BacktestTradeResolver()
    assert resolver.resolve(plan(), low=Decimal("94"), high=Decimal("101")).outcome is TradeOutcome.SL
    result = resolver.resolve(plan(), low=Decimal("99"), high=Decimal("106"))
    assert result.outcome is TradeOutcome.TP1
    assert not result.ambiguous_intrabar


def test_same_candle_long_collision_is_conservative_sl_first():
    result = BacktestTradeResolver().resolve(plan(), low=Decimal("94"), high=Decimal("106"))
    assert result.outcome is TradeOutcome.SL
    assert result.resolution_method is ResolutionMethod.SAME_CANDLE_SL_FIRST
    assert result.ambiguous_intrabar is True


def test_short_entry_and_collision_are_resolved_sl_first():
    result = BacktestTradeResolver().resolve(plan(CSDDirection.BEARISH), low=Decimal("94"), high=Decimal("106"))
    assert result.entered and result.outcome is TradeOutcome.SL
    assert result.resolution_method is ResolutionMethod.SAME_CANDLE_SL_FIRST


def test_candle_that_does_not_touch_entry_remains_pending():
    result = BacktestTradeResolver().resolve(plan(), low=Decimal("101"), high=Decimal("104"))
    assert not result.entered and result.outcome is TradeOutcome.PENDING
