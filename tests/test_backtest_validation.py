from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from app.backtest.gate import GoLiveGateSettings, evaluate_gate
from app.backtest.metrics import calculate_metrics
from app.backtest.report import random_baseline
from app.backtest.walkforward import rolling_windows
from app.backtests import TradeAudit


def trade(index, value):
    when = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)
    return TradeAudit(str(index), "run", when, "BULLISH", Decimal("100"), Decimal("99"), Decimal("101"), None, None,
                      Decimal(value), "GOOD_SIGNAL", when, "TP1", Decimal(value), Decimal("0.1"), Decimal(value), "TP_ONLY", False)


def test_metrics_are_net_and_include_wilson_and_buckets():
    metrics = calculate_metrics([trade(0, "1"), trade(1, "-0.5")])
    assert metrics.trade_count == 2
    assert metrics.total_r == Decimal("0.5")
    assert metrics.win_rate_ci_low <= metrics.win_rate <= metrics.win_rate_ci_high
    assert metrics.by_direction["BULLISH"]["trades"] == 2


def test_random_baseline_is_reproducible():
    trades = [trade(0, "1"), trade(1, "-0.5"), trade(2, "0.2")]
    assert random_baseline(trades, iterations=50) == random_baseline(trades, iterations=50)


def test_walk_forward_windows_and_gate_failure_are_explicit():
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    windows = rolling_windows(start, datetime(2022, 1, 1, tzinfo=timezone.utc))
    assert windows and windows[0].out_sample_start == windows[0].in_sample_end
    result = evaluate_gate({"status": "DIAGNOSTIC", "trade_count": 1}, GoLiveGateSettings())
    assert not result.passed
    assert result.observation_mode
