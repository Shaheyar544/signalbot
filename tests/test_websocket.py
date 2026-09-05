import json

import pytest

from app.data.binance_ws import BinanceWebSocketClient, ReconnectBackoff
from app.data.candles import CandleStore
from app.events.bus import EventBus
from app.monitoring.health import HealthStatus


def kline(symbol="ETHUSDT", closed=False, open_time=1735689600000, close="101"):
    high = str(max(102, int(close)))
    low = str(min(99, int(close)))
    return {"stream": f"{symbol.lower()}@kline_15m", "data": {"k": {
        "s": symbol, "i": "15m", "t": open_time, "T": open_time + 899999,
        "o": "100", "h": high, "l": low, "c": close, "v": "12.5", "x": closed,
    }}}


@pytest.mark.asyncio
async def test_ws_parses_forming_then_closed_once():
    events = []
    bus = EventBus()
    bus.subscribe_candle_closed(lambda event: events.append(event))
    store, health = CandleStore(), HealthStatus()
    client = BinanceWebSocketClient(("ETHUSDT",), ("15m",), store, bus, health)
    await client.process_message(json.dumps(kline(closed=False)))
    assert events == []
    await client.process_message(kline(closed=True))
    await client.process_message(kline(closed=True))
    assert len(events) == 1
    assert events[0].candle.is_closed
    assert health.timeframe_healthy("ETHUSDT", "15m")


@pytest.mark.asyncio
async def test_ws_relays_each_intrabar_update_without_extra_closed_events():
    updates = []
    client = BinanceWebSocketClient(("ETHUSDT",), ("15m",), CandleStore(), EventBus(), HealthStatus(), on_candle_update=updates.append)
    await client.process_message(kline(closed=False, close="101"))
    await client.process_message(kline(closed=False, close="102"))
    assert [str(item.close) for item in updates] == ["101", "102"]
    assert not updates[-1].is_closed


@pytest.mark.asyncio
async def test_ws_maintains_simultaneous_pairs_without_collision():
    events = []
    bus = EventBus(); bus.subscribe_candle_closed(lambda event: events.append(event.symbol))
    store = CandleStore()
    client = BinanceWebSocketClient(("ETHUSDT", "BTCUSDT"), ("15m",), store, bus, HealthStatus())
    await client.process_message(kline("ETHUSDT", closed=True, close="3000"))
    await client.process_message(kline("BTCUSDT", closed=True, close="90000"))
    assert events == ["ETHUSDT", "BTCUSDT"]
    assert str(store.get_latest("ETHUSDT", "15m").close) == "3000"
    assert str(store.get_latest("BTCUSDT", "15m").close) == "90000"


@pytest.mark.asyncio
async def test_ws_ignores_malformed_and_unsubscribed_messages():
    store = CandleStore()
    client = BinanceWebSocketClient(("ETHUSDT",), ("15m",), store, EventBus(), HealthStatus())
    await client.process_message("not json")
    await client.process_message(kline("BTCUSDT", closed=True))
    assert store.get_latest("ETHUSDT", "15m") is None


def test_stream_names_are_dynamic_and_lowercase():
    client = BinanceWebSocketClient(("ETHUSDT", "BTCUSDT"), ("15m", "1h", "4h"), CandleStore(), EventBus(), HealthStatus())
    assert client.stream_names == ("ethusdt@kline_15m", "ethusdt@kline_1h", "ethusdt@kline_4h", "btcusdt@kline_15m", "btcusdt@kline_1h", "btcusdt@kline_4h")


def test_reconnect_backoff_caps_and_resets():
    backoff = ReconnectBackoff(5)
    assert [backoff.next_delay() for _ in range(5)] == [1, 2, 4, 5, 5]
    backoff.reset()
    assert backoff.next_delay() == 1


def test_rest_websocket_reconciliation_deduplicates_and_sorts(make_candle):
    store = CandleStore()
    rest = [make_candle(offset=2), make_candle(offset=0), make_candle(offset=1)]
    websocket_update = make_candle(offset=1, close="103")
    for candle in rest:
        store.add_candle(candle)
    store.add_candle(websocket_update)
    reconciled = store.get_recent("ETHUSDT", "15m", 10)
    assert [item.open_time for item in reconciled] == sorted(item.open_time for item in reconciled)
    assert len(reconciled) == 3
    assert reconciled[1].close == websocket_update.close


@pytest.mark.asyncio
async def test_stop_is_graceful_without_connection():
    client = BinanceWebSocketClient(("ETHUSDT",), ("15m",), CandleStore(), EventBus(), HealthStatus())
    await client.stop()
    assert client._stop.is_set()
