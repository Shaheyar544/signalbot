from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.events.models import Candle


@pytest.fixture
def make_candle():
    def factory(symbol="ETHUSDT", timeframe="15m", offset=0, closed=True, close="101"):
        start = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=15 * offset)
        closing_price = Decimal(close)
        return Candle(symbol, timeframe, start, start + timedelta(minutes=15) - timedelta(milliseconds=1), Decimal("100"), max(Decimal("102"), closing_price), min(Decimal("99"), closing_price), closing_price, Decimal("12.5"), closed)
    return factory
