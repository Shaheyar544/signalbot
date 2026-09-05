from decimal import Decimal

from app.structure.market_structure import MarketStructureEngine, StructureKind
from app.structure.swings import SwingPoint, SwingType


def _swing(candle, kind, price):
    return SwingPoint(candle.symbol, candle.timeframe, candle.open_time, Decimal(str(price)), kind, candle)


def test_structure_engine_classifies_higher_and_lower_swings(make_candle):
    candles = [make_candle(offset=index) for index in range(4)]
    swings = [
        _swing(candles[0], SwingType.LOW, 90),
        _swing(candles[1], SwingType.HIGH, 110),
        _swing(candles[2], SwingType.LOW, 95),
        _swing(candles[3], SwingType.HIGH, 115),
    ]

    events = MarketStructureEngine().evaluate("ETHUSDT", "15m", swings)

    assert [event.kind for event in events] == [None, None, StructureKind.HL, StructureKind.HH]


def test_structure_engine_state_is_independent_per_pair(make_candle):
    eth_candles = [make_candle("ETHUSDT", offset=index) for index in range(2)]
    btc_candles = [make_candle("BTCUSDT", offset=index) for index in range(2)]
    engine = MarketStructureEngine()

    engine.evaluate("ETHUSDT", "15m", [_swing(eth_candles[0], SwingType.HIGH, 100), _swing(eth_candles[1], SwingType.HIGH, 110)])
    btc_events = engine.evaluate("BTCUSDT", "15m", [_swing(btc_candles[0], SwingType.HIGH, 100), _swing(btc_candles[1], SwingType.HIGH, 90)])

    assert btc_events[-1].kind is StructureKind.LH
