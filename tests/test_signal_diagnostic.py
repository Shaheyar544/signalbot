from datetime import timedelta

import pytest

from app.backtest.signal_diagnostic import seven_day_signal_report
from app.config.settings import load_settings


@pytest.mark.asyncio
async def test_seven_day_signal_diagnostic_is_eth_only_closed_and_does_not_mutate_settings(make_candle):
    settings = load_settings("tests/fixtures/settings.yaml")
    original_symbols, original_timeframes = settings.historical.symbols, settings.timeframes
    first = make_candle(symbol="ETHUSDT", timeframe="15m", offset=0)
    closed = [make_candle(symbol="ETHUSDT", timeframe="15m", offset=index) for index in range(1, 4)]
    forming = make_candle(symbol="ETHUSDT", timeframe="15m", offset=4, closed=False)
    report = await seven_day_signal_report(settings, [first, *closed, forming],
                                           start=first.open_time, end=first.open_time + timedelta(days=7))

    assert report["validation_scope"] == "ETHUSDT_7DAY_SIGNAL_TEST"
    assert report["methodology"]["forming_candles_excluded"] is True
    assert report["data"]["timeframes"]["15m"]["candle_count"] == 4
    assert settings.historical.symbols == original_symbols
    assert settings.timeframes == original_timeframes
