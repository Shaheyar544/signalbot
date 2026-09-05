from dataclasses import replace
from decimal import Decimal

from app.structure.swings import SwingDetector, SwingType


def _with_prices(candle, high: int, low: int):
    return replace(candle, open=Decimal(str(low)), high=Decimal(str(high)), low=Decimal(str(low)), close=Decimal(str(low)))


def test_detector_confirms_a_swing_high_only_after_right_bars(make_candle):
    candles = [_with_prices(make_candle(offset=index), high, 1) for index, high in enumerate((2, 3, 7, 3, 2))]

    swings = SwingDetector(left_bars=2, right_bars=2).detect(candles)

    assert len(swings) == 1
    assert swings[0].kind is SwingType.HIGH
    assert swings[0].candle.open_time == candles[2].open_time
    assert swings[0].price == Decimal("7")


def test_detector_keeps_symbols_and_timeframes_isolated(make_candle):
    eth = [_with_prices(make_candle("ETHUSDT", offset=index), high, 1) for index, high in enumerate((2, 3, 7, 3, 2))]
    btc = [_with_prices(make_candle("BTCUSDT", offset=index), high, 1) for index, high in enumerate((2, 8, 3, 2, 1))]
    detector = SwingDetector(left_bars=1, right_bars=1)

    eth_swings, btc_swings = detector.detect(eth), detector.detect(btc)

    assert {s.symbol for s in eth_swings} == {"ETHUSDT"}
    assert {s.symbol for s in btc_swings} == {"BTCUSDT"}


def test_equal_highs_are_not_swing_points(make_candle):
    candles = [_with_prices(make_candle(offset=index), high, 1) for index, high in enumerate((2, 7, 7, 3, 2))]

    assert SwingDetector(left_bars=1, right_bars=1).detect(candles) == []
