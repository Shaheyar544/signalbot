from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone, timedelta
import asyncio
import logging
from typing import Any

import aiohttp

from app.events.models import Candle, utc_from_millis
from app.data.binance_ws import ReconnectBackoff

LOGGER = logging.getLogger(__name__)
REST_BASE_URL = "https://fapi.binance.com"


class BinanceRestClient:
    """Unauthenticated Binance USD-M Futures market-data adapter."""
    def __init__(self, session: aiohttp.ClientSession | None = None, base_url: str = REST_BASE_URL) -> None:
        self._session = session
        self._owns_session = session is None
        self.base_url = base_url.rstrip("/")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
        self._session = None

    async def validate_symbol(self, symbol: str) -> bool:
        session = await self._get_session()
        try:
            async with session.get(f"{self.base_url}/fapi/v1/exchangeInfo", params={"symbol": symbol}) as response:
                if response.status != 200:
                    LOGGER.warning("Binance symbol validation failed for %s: HTTP %s", symbol, response.status)
                    return False
                payload = await response.json()
        except (aiohttp.ClientError, TimeoutError) as error:
            LOGGER.error("Binance REST symbol validation failed for %s: %s", symbol, error)
            return False
        return any(item.get("symbol") == symbol and item.get("status") == "TRADING" for item in payload.get("symbols", []))

    async def fetch_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        session = await self._get_session()
        try:
            async with session.get(f"{self.base_url}/fapi/v1/klines", params={"symbol": symbol, "interval": timeframe, "limit": limit}) as response:
                response.raise_for_status()
                rows: list[list[Any]] = await response.json()
        except (aiohttp.ClientError, TimeoutError) as error:
            LOGGER.error("Binance REST candle request failed for %s %s: %s", symbol, timeframe, error)
            raise RuntimeError(f"Cannot fetch {symbol} {timeframe} candles") from error
        return sorted((self.candle_from_rest_row(symbol, timeframe, row) for row in rows), key=lambda item: item.open_time)

    async def fetch_candles_range(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[Candle]:
        """Fetch a complete half-open range using Binance's 1500-row pages."""
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")
        if start >= end:
            return []
        session = await self._get_session()
        cursor = start.astimezone(timezone.utc)
        end = end.astimezone(timezone.utc)
        collected: dict[datetime, Candle] = {}
        backoff = ReconnectBackoff(60)
        failures = 0
        while cursor < end:
            params = {"symbol": symbol, "interval": timeframe,
                      "startTime": int(cursor.timestamp() * 1000),
                      "endTime": int(end.timestamp() * 1000), "limit": 1500}
            async with session.get(f"{self.base_url}/fapi/v1/klines", params=params) as response:
                if response.status in (418, 429) or response.status >= 500:
                    failures += 1
                    if failures >= 5:
                        raise RuntimeError(f"Binance candle range request failed after 5 failures for {symbol} {timeframe}")
                    retry_after = response.headers.get("Retry-After") if response.headers else None
                    delay = float(retry_after) if retry_after is not None else backoff.next_delay()
                    await asyncio.sleep(delay)
                    continue
                if response.status >= 400:
                    response.raise_for_status()
                rows: list[list[Any]] = await response.json()
            failures = 0
            backoff.reset()
            page = [self.candle_from_rest_row(symbol, timeframe, row) for row in rows]
            for candle in page:
                if start <= candle.open_time < end:
                    collected[candle.open_time] = candle
            if len(rows) < 1500:
                break
            if not page:
                break
            last = max(page, key=lambda candle: candle.open_time)
            next_cursor = last.close_time + timedelta(milliseconds=1)
            if next_cursor <= cursor:
                raise RuntimeError("Binance candle pagination did not advance")
            cursor = next_cursor
            await asyncio.sleep(0.25)
        return sorted(collected.values(), key=lambda candle: candle.open_time)

    @staticmethod
    def candle_from_rest_row(symbol: str, timeframe: str, row: list[Any]) -> Candle:
        close_time = utc_from_millis(row[6])
        return Candle(symbol, timeframe, utc_from_millis(row[0]), close_time, Decimal(row[1]), Decimal(row[2]), Decimal(row[3]), Decimal(row[4]), Decimal(row[5]), close_time <= datetime.now(timezone.utc))
