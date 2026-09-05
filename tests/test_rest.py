from app.data.binance_rest import BinanceRestClient


def test_historical_candles_are_ordered_and_closed():
    rows = [
        [1735690500000, "100", "102", "99", "101", "2", 1735691399999],
        [1735689600000, "99", "101", "98", "100", "1", 1735690499999],
    ]
    candles = sorted((BinanceRestClient.candle_from_rest_row("ETHUSDT", "15m", row) for row in rows), key=lambda candle: candle.open_time)
    assert [str(candle.close) for candle in candles] == ["100", "101"]
    assert all(candle.is_closed for candle in candles)
