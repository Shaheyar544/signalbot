import pytest

from app.main import validate_enabled_symbols


class FakeRestClient:
    async def validate_symbol(self, symbol: str) -> bool:
        return symbol != "INVALIDPAIR"


@pytest.mark.asyncio
async def test_validates_enabled_symbols_without_async_generator_error():
    assert await validate_enabled_symbols(FakeRestClient(), ("ETHUSDT", "INVALIDPAIR", "BTCUSDT")) == ("ETHUSDT", "BTCUSDT")
