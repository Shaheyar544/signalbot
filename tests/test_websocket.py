import json
from types import SimpleNamespace

import pytest

from app.data.binance_ws import BinanceWebSocketClient, ReconnectBackoff, WS_BASE_URL
from app.data.candles import CandleStore
from app.events.bus import EventBus
from app.monitoring.health import HealthStatus
from app.strategy.csd_strategy import CSDStrategyEngine


def kline(symbol="ETHUSDT", closed=False, open_time=1735689600000, close="101", timeframe="15m"):
    high = str(max(102, int(close)))
    low = str(min(99, int(close)))
    return {"stream": f"{symbol.lower()}@kline_{timeframe}", "data": {"k": {
        "s": symbol, "i": timeframe, "t": open_time, "T": open_time + 899999,
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
async def test_closed_one_day_websocket_candle_updates_configured_strategy_indicator_state():
    store, bus, health = CandleStore(), EventBus(), HealthStatus()
    strategy = CSDStrategyEngine(store, "15m", confirmation_timeframes=("1h", "4h", "1d"))
    bus.subscribe_candle_closed(strategy.on_candle_closed)
    client = BinanceWebSocketClient(("ETHUSDT",), ("15m", "1h", "4h", "1d"), store, bus, health)

    await client.process_message(kline(closed=True, timeframe="1d"))

    assert health.timeframe_healthy("ETHUSDT", "1d")
    assert ("ETHUSDT", "1d") in strategy.latest_indicators


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
    client = BinanceWebSocketClient(("ETHUSDT", "BTCUSDT"), ("15m", "1h", "4h", "1d"), CandleStore(), EventBus(), HealthStatus())
    assert client.stream_names == ("ethusdt@kline_15m", "ethusdt@kline_1h", "ethusdt@kline_4h", "ethusdt@kline_1d",
                                   "btcusdt@kline_15m", "btcusdt@kline_1h", "btcusdt@kline_4h", "btcusdt@kline_1d")


def test_default_websocket_endpoint_uses_binance_market_route_for_klines():
    """Kline streams are market streams; the legacy root route emits none."""
    assert WS_BASE_URL == "wss://fstream.binance.com/market/ws"


@pytest.mark.asyncio
async def test_explicit_subscription_requires_binance_acknowledgement():
    class WebSocket:
        def __init__(self): self.requests = []
        async def send_json(self, request): self.requests.append(request)
        async def receive(self, timeout):
            response = ('{"result":null,"id":1}' if len(self.requests) == 1 else '{"result":["ethusdt@kline_15m","ethusdt@kline_1h","ethusdt@kline_4h"],"id":2}')
            return SimpleNamespace(type=__import__('aiohttp').WSMsgType.TEXT, data=response)

    health = HealthStatus()
    client = BinanceWebSocketClient(("ETHUSDT",), ("15m", "1h", "4h"), CandleStore(), EventBus(), health)
    client._websocket = WebSocket()
    await client._subscribe()
    assert client._websocket.requests == [{"method": "SUBSCRIBE", "params": ["ethusdt@kline_15m", "ethusdt@kline_1h", "ethusdt@kline_4h"], "id": 1}, {"method": "LIST_SUBSCRIPTIONS", "id": 2}]
    assert health.subscription_acknowledged
    assert health.active_subscriptions == client.stream_names


@pytest.mark.asyncio
async def test_subscription_verification_processes_an_interleaved_kline_event():
    class WebSocket:
        def __init__(self):
            self.requests = []
            self.responses = iter((
                '{"result":null,"id":1}',
                json.dumps(kline("ETHUSDT", closed=False)),
                '{"result":["ethusdt@kline_15m"],"id":2}',
            ))

        async def send_json(self, request):
            self.requests.append(request)

        async def receive(self, timeout):
            return SimpleNamespace(type=__import__('aiohttp').WSMsgType.TEXT, data=next(self.responses))

    store, health = CandleStore(), HealthStatus()
    client = BinanceWebSocketClient(("ETHUSDT",), ("15m",), store, EventBus(), health)
    client._websocket = WebSocket()
    await client._subscribe()
    assert health.subscription_acknowledged
    assert health.messages_by_stream == {("ETHUSDT", "15m"): 1}
    assert store.get_latest("ETHUSDT", "15m") is not None


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
