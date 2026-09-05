from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from decimal import Decimal
import json
import logging
from typing import Any

import aiohttp

from app.data.candles import CandleStore
from app.events.bus import EventBus
from app.events.models import Candle, CandleClosedEvent, utc_from_millis
from app.monitoring.health import HealthStatus

LOGGER = logging.getLogger(__name__)
WS_BASE_URL = "wss://fstream.binance.com/stream?streams="
ReconcileCallback = Callable[[], Awaitable[None]]


class ReconnectBackoff:
    def __init__(self, maximum_seconds: int) -> None:
        self.maximum_seconds = maximum_seconds
        self.attempt = 0

    def next_delay(self) -> int:
        delay = min(2**self.attempt, self.maximum_seconds)
        self.attempt += 1
        return delay

    def reset(self) -> None:
        self.attempt = 0


class BinanceWebSocketClient:
    def __init__(
        self, symbols: tuple[str, ...], timeframes: tuple[str, ...], store: CandleStore,
        bus: EventBus, health: HealthStatus, max_reconnect_delay_seconds: int = 60,
        receive_timeout_seconds: int = 90, session: aiohttp.ClientSession | None = None,
        base_url: str = WS_BASE_URL, on_health_update: Callable[[], None] | None = None,
        on_candle_update: Callable[[Candle], None] | None = None,
    ) -> None:
        self.symbols, self.timeframes = symbols, timeframes
        self.store, self.bus, self.health = store, bus, health
        self.max_reconnect_delay_seconds = max_reconnect_delay_seconds
        self.receive_timeout_seconds = receive_timeout_seconds
        self._session, self._owns_session = session, session is None
        self.base_url = base_url
        self.on_health_update = on_health_update
        self.on_candle_update = on_candle_update
        self._stop = asyncio.Event()
        self._websocket: aiohttp.ClientWebSocketResponse | None = None

    @property
    def stream_names(self) -> tuple[str, ...]:
        return tuple(f"{symbol.lower()}@kline_{timeframe}" for symbol in self.symbols for timeframe in self.timeframes)

    async def stop(self) -> None:
        self._stop.set()
        if self._websocket is not None:
            await self._websocket.close()

    def _notify_health_update(self) -> None:
        if self.on_health_update is None:
            return
        try:
            self.on_health_update()
        except Exception as error:  # Health publishing must not interrupt market data.
            LOGGER.warning("Could not publish runtime health: %s", error)

    async def run(self, reconcile: ReconcileCallback) -> None:
        if not self.stream_names:
            LOGGER.warning("No valid enabled symbols; WebSocket will not start")
            return
        session = self._session or aiohttp.ClientSession()
        self._session = session
        backoff = ReconnectBackoff(self.max_reconnect_delay_seconds)
        first_connection = True
        try:
            while not self._stop.is_set():
                try:
                    url = self.base_url + "/".join(self.stream_names)
                    self._websocket = await session.ws_connect(url, heartbeat=30, receive_timeout=self.receive_timeout_seconds)
                    self.health.websocket_connected = True
                    self._notify_health_update()
                    LOGGER.info("WebSocket connected (%d streams)", len(self.stream_names))
                    if not first_connection:
                        await reconcile()
                    first_connection = False
                    backoff.reset()
                    async for message in self._websocket:
                        if self._stop.is_set():
                            break
                        if message.type == aiohttp.WSMsgType.TEXT:
                            await self.process_message(message.data)
                        elif message.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                            break
                except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as error:
                    if not self._stop.is_set():
                        LOGGER.warning("WebSocket disconnected: %s", error)
                finally:
                    self.health.websocket_connected = False
                    self._notify_health_update()
                    self._websocket = None
                if self._stop.is_set() or not self.max_reconnect_delay_seconds:
                    break
                delay = backoff.next_delay()
                LOGGER.info("WebSocket reconnecting in %ss", delay)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
        finally:
            if self._owns_session and session is not None:
                await session.close()
            self._session = None

    async def process_message(self, raw_message: str | dict[str, Any]) -> None:
        try:
            payload = json.loads(raw_message) if isinstance(raw_message, str) else raw_message
            kline = payload.get("data", payload).get("k")
            if not isinstance(kline, dict):
                raise ValueError("not a kline payload")
            candle = self.candle_from_kline(kline)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            LOGGER.warning("Ignoring malformed WebSocket message: %s", error)
            return
        if candle.symbol not in self.symbols or candle.timeframe not in self.timeframes:
            LOGGER.warning("Ignoring unexpected stream %s %s", candle.symbol, candle.timeframe)
            return
        self.health.record_message()
        self._notify_health_update()
        previous_candle = self.store.get(candle.symbol, candle.timeframe, candle.open_time)
        self.store.add_candle(candle)
        if self.on_candle_update is not None:
            try:
                self.on_candle_update(candle)
            except Exception as error:  # Dashboard publication must never affect the engine.
                LOGGER.warning("Could not publish live candle: %s", error)
        if candle.is_closed and (previous_candle is None or not previous_candle.is_closed):
            self.health.record_closed_candle(candle)
            self._notify_health_update()
            LOGGER.info("%s %s candle closed", candle.symbol, candle.timeframe)
            await self.bus.publish_candle_closed(CandleClosedEvent(candle.symbol, candle.timeframe, candle))

    @staticmethod
    def candle_from_kline(kline: dict[str, Any]) -> Candle:
        return Candle(
            symbol=str(kline["s"]).upper(), timeframe=str(kline["i"]).lower(),
            open_time=utc_from_millis(kline["t"]), close_time=utc_from_millis(kline["T"]),
            open=Decimal(str(kline["o"])), high=Decimal(str(kline["h"])), low=Decimal(str(kline["l"])),
            close=Decimal(str(kline["c"])), volume=Decimal(str(kline["v"])), is_closed=bool(kline["x"]),
        )
