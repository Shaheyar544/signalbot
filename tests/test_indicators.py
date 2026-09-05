from decimal import Decimal

from app.indicators.engine import IndicatorEngine


def test_indicator_engine_calculates_ema_from_closed_candle_closes(make_candle):
    candles = [make_candle(offset=index, close=str(close)) for index, close in enumerate((10, 11, 12))]

    values = IndicatorEngine(ema_periods=(3,)).calculate(candles)

    # EMA(3): 10; 10.5; 11.25
    assert values.ema[3] == Decimal("11.25")


def test_indicator_engine_returns_rsi_macd_bollinger_and_volume_values(make_candle):
    closes = tuple(range(1, 31))
    candles = [make_candle(offset=index, close=str(close)) for index, close in enumerate(closes)]
    engine = IndicatorEngine(ema_periods=(10,), rsi_period=14, macd_fast=12, macd_slow=26, macd_signal=9, bollinger_period=20, volume_period=20)

    values = engine.calculate(candles)

    assert values.rsi == Decimal("100")
    assert values.macd is not None and values.macd.histogram > 0
    assert values.bollinger is not None and values.bollinger.middle == Decimal("20.5")
    assert values.volume_sma == Decimal("12.5")
    assert values.volume_ratio == Decimal("1")


def test_indicator_engine_excludes_forming_candles(make_candle):
    candles = [make_candle(offset=0, close="10"), make_candle(offset=1, close="20"), make_candle(offset=2, close="1000", closed=False)]

    values = IndicatorEngine(ema_periods=(2,)).calculate(candles)

    assert values.ema[2] == Decimal(str(Decimal("16.66666666666666666666666667")))


def test_indicator_engine_calculates_wilder_atr_from_closed_ohlcv(make_candle):
    candles = [
        make_candle(offset=0, close="100"),
        make_candle(offset=1, close="102"),
        make_candle(offset=2, close="101"),
    ]

    values = IndicatorEngine(ema_periods=(2,), atr_period=2).calculate(candles)

    # Every fixture candle spans 3 points (102 - 99), so ATR(2) is 3.
    assert values.atr == Decimal("3")


def test_indicator_engine_atr_ignores_a_forming_extreme_candle(make_candle):
    closed = [make_candle(offset=index, close=str(100 + index)) for index in range(3)]
    forming = make_candle(offset=3, close="1000", closed=False)
    forming = forming.__class__(
        forming.symbol, forming.timeframe, forming.open_time, forming.close_time,
        forming.open, Decimal("2000"), Decimal("1"), forming.close, forming.volume, forming.is_closed,
    )
    engine = IndicatorEngine(ema_periods=(2,), atr_period=2)

    assert engine.calculate([*closed, forming]).atr == engine.calculate(closed).atr
