from datetime import datetime, timedelta, timezone

import aiohttp
import pytest

from app.data.binance_rest import BinanceRestClient


def _row(index: int) -> list[object]:
    opened = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=15 * index)
    open_ms = int(opened.timestamp() * 1000)
    return [open_ms, "100", "101", "99", "100.5", "2", open_ms + 899999]


class _Response:
    def __init__(self, status, rows=None, headers=None):
        self.status, self._rows, self.headers = status, rows or [], headers or {}

    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False
    async def json(self): return self._rows
    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(None, (), status=self.status)


class _Session:
    def __init__(self, responses): self.responses, self.calls = list(responses), []
    def get(self, url, params):
        self.calls.append(params)
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_range_fetch_paginates_three_pages_and_deduplicates(monkeypatch):
    responses = [_Response(200, [_row(i) for i in range(1500)]),
                 _Response(200, [_row(i) for i in range(1499, 2999)]),
                 _Response(200, [_row(i) for i in range(2999, 4000)])]
    session = _Session(responses)
    async def sleep(_seconds):
        return None
    monkeypatch.setattr("asyncio.sleep", sleep)
    client = BinanceRestClient(session=session)
    candles = await client.fetch_candles_range("ETHUSDT", "15m", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 2, 15, tzinfo=timezone.utc))
    assert len(session.calls) == 3
    assert len(candles) == 4000
    assert candles == sorted(candles, key=lambda candle: candle.open_time)
    assert len({candle.open_time for candle in candles}) == 4000
    assert all(call["limit"] == 1500 for call in session.calls)


@pytest.mark.asyncio
async def test_rate_limit_retries_same_page_with_retry_after(monkeypatch):
    responses = [_Response(429, headers={"Retry-After": "0"}), _Response(200, [_row(0)])]
    session = _Session(responses)
    sleeps = []
    async def sleep(seconds): sleeps.append(seconds)
    monkeypatch.setattr("asyncio.sleep", sleep)
    candles = await BinanceRestClient(session=session).fetch_candles_range("ETHUSDT", "15m", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 1, 2, tzinfo=timezone.utc))
    assert len(candles) == 1
    assert len(session.calls) == 2
    assert sleeps[0] == 0


@pytest.mark.asyncio
async def test_persistent_page_failures_are_bounded(monkeypatch):
    session = _Session([_Response(500) for _ in range(6)])
    async def sleep(_seconds):
        return None
    monkeypatch.setattr("asyncio.sleep", sleep)
    with pytest.raises(RuntimeError, match="after 5 failures"):
        await BinanceRestClient(session=session).fetch_candles_range("ETHUSDT", "15m", datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 1, 2, tzinfo=timezone.utc))
