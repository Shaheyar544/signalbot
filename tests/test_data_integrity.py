from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.backtest.data_integrity import check_integrity
from app.events.models import Candle


def candles(count=5):
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return [Candle("ETHUSDT", "15m", start + timedelta(minutes=15 * i),
                    start + timedelta(minutes=15 * i + 15) - timedelta(milliseconds=1),
                    Decimal("100"), Decimal("101"), Decimal("99"), Decimal("100"), Decimal("1"), True)
            for i in range(count)]


def test_clean_series_is_clean():
    report = check_integrity("ETHUSDT", "15m", candles())
    assert report.is_clean
    assert report.gaps == ()


def test_one_missing_candle_is_reported():
    series = candles()
    report = check_integrity("ETHUSDT", "15m", series[:2] + series[3:])
    assert not report.is_clean
    assert len(report.gaps) == 1
    assert report.gaps[0].missing_candles == 1


def test_duplicate_open_time_is_reported():
    series = candles()
    report = check_integrity("ETHUSDT", "15m", series + [series[2]])
    assert not report.is_clean
    assert report.duplicate_open_times == 1


def test_multiple_gaps_are_reported():
    series = candles(8)
    report = check_integrity("ETHUSDT", "15m", [series[0], series[3], series[7]])
    assert len(report.gaps) == 2
    assert sum(g.missing_candles for g in report.gaps) == 5


def test_empty_series_is_not_clean():
    report = check_integrity("ETHUSDT", "15m", [])
    assert not report.is_clean
    assert report.empty
