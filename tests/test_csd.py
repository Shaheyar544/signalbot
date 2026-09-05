from dataclasses import replace
from decimal import Decimal

from app.structure.csd import CSDEngine, CSDDirection
from app.structure.market_structure import StructureEvent, StructureKind
from app.structure.swings import SwingPoint, SwingType


def _event(candle, swing_kind, price, structure_kind):
    swing = SwingPoint(candle.symbol, candle.timeframe, candle.open_time, Decimal(str(price)), swing_kind, candle)
    return StructureEvent(candle.symbol, candle.timeframe, swing, structure_kind)


def test_csd_engine_emits_bullish_event_for_closed_break_above_bearish_swing(make_candle):
    resistance = make_candle(offset=1, close="100")
    prior_bearish_structure = [_event(resistance, SwingType.HIGH, 100, StructureKind.LH)]
    closed_break = replace(make_candle(offset=2, close="101"), high=Decimal("102"))

    event = CSDEngine(minimum_close_distance_percent=Decimal("0.5")).evaluate(closed_break, prior_bearish_structure)

    assert event is not None
    assert event.direction is CSDDirection.BULLISH
    assert event.broken_swing.price == Decimal("100")


def test_csd_engine_rejects_wick_only_break_and_forming_candle(make_candle):
    resistance = make_candle(offset=1, close="100")
    structure = [_event(resistance, SwingType.HIGH, 100, StructureKind.LH)]
    wick_only = replace(make_candle(offset=2, close="99"), high=Decimal("101"))
    forming_break = replace(make_candle(offset=3, close="101", closed=False), high=Decimal("102"))
    engine = CSDEngine(minimum_close_distance_percent=Decimal("0.5"))

    assert engine.evaluate(wick_only, structure) is None
    assert engine.evaluate(forming_break, structure) is None


def test_csd_engine_emits_bearish_event_for_closed_break_below_bullish_swing(make_candle):
    support = make_candle(offset=1, close="100")
    prior_bullish_structure = [_event(support, SwingType.LOW, 100, StructureKind.HL)]
    closed_break = replace(make_candle(offset=2, close="99"), low=Decimal("98"))

    event = CSDEngine(minimum_close_distance_percent=Decimal("0.5")).evaluate(closed_break, prior_bullish_structure)

    assert event is not None
    assert event.direction is CSDDirection.BEARISH


def test_csd_engine_does_not_repeat_the_same_swing_break(make_candle):
    resistance = make_candle(offset=1, close="100")
    structure = [_event(resistance, SwingType.HIGH, 100, StructureKind.LH)]
    first_break = replace(make_candle(offset=2, close="101"), high=Decimal("102"))
    later_break = replace(make_candle(offset=3, close="102"), high=Decimal("103"))
    engine = CSDEngine(minimum_close_distance_percent=Decimal("0.5"))

    assert engine.evaluate(first_break, structure) is not None
    assert engine.evaluate(later_break, structure) is None


def test_csd_engine_supports_an_atr_based_close_threshold(make_candle):
    resistance = make_candle(offset=1, close="100")
    structure = [_event(resistance, SwingType.HIGH, 100, StructureKind.LH)]
    weak_break = replace(make_candle(offset=2, close="100.4"), high=Decimal("101"))
    valid_break = replace(make_candle(offset=3, close="100.8"), high=Decimal("101"))
    engine = CSDEngine(
        minimum_close_distance_percent=Decimal("0.05"),
        breakout_method="atr",
        minimum_close_atr=Decimal("0.15"),
    )

    assert engine.evaluate(weak_break, structure, atr=Decimal("3")) is None
    event = engine.evaluate(valid_break, structure, atr=Decimal("3"))
    assert event is not None
    assert event.close_distance_atr == Decimal("0.2666666666666666666666666667")


def test_csd_engine_requires_an_available_positive_atr_in_atr_mode(make_candle):
    resistance = make_candle(offset=1, close="100")
    structure = [_event(resistance, SwingType.HIGH, 100, StructureKind.LH)]
    candle = replace(make_candle(offset=2, close="101"), high=Decimal("102"))
    engine = CSDEngine(breakout_method="atr", minimum_close_atr=Decimal("0.15"))

    assert engine.evaluate(candle, structure, atr=None) is None
    assert engine.evaluate(candle, structure, atr=Decimal(0)) is None
