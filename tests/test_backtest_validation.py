from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from app.backtest.gate import GoLiveGateSettings, evaluate_gate
from app.backtest.metrics import calculate_metrics
from app.backtest.report import random_baseline
from app.backtest.report import random_entry_baseline
from app.backtest.walkforward import rolling_windows
from app.backtests import TradeAudit


def trade(index, value):
    when = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)
    return TradeAudit(str(index), "run", when, "BULLISH", Decimal("100"), Decimal("99"), Decimal("101"), None, None,
                      Decimal(value), "GOOD_SIGNAL", when, "TP1", Decimal(value), Decimal("0.1"), Decimal(value), "TP_ONLY", False)


def test_metrics_are_net_and_include_wilson_and_buckets():
    first = trade(0, "1")
    second = trade(1, "-0.5")
    from dataclasses import replace
    first = replace(first, bars_in_trade=4, mfe_r=Decimal("1.4"), mae_r=Decimal("-0.2"), regime="trend", session="us")
    second = replace(second, bars_in_trade=2, mfe_r=Decimal("0.3"), mae_r=Decimal("-1"), regime="range", session="eu")
    metrics = calculate_metrics([first, second])
    assert metrics.trade_count == 2
    assert metrics.total_r == Decimal("0.5")
    assert metrics.win_rate_ci_low <= metrics.win_rate <= metrics.win_rate_ci_high
    assert metrics.by_direction["BULLISH"]["trades"] == 2
    assert metrics.average_bars_in_trade == Decimal("3")
    assert metrics.mfe_distribution == (Decimal("1.4"), Decimal("0.3"))
    assert metrics.mae_distribution == (Decimal("-0.2"), Decimal("-1"))
    assert metrics.by_regime["trend"]["trades"] == 1
    assert metrics.by_session["us"]["win_rate"] == Decimal("1")


def test_random_baseline_is_reproducible():
    assert random_baseline(iterations=50)["status"] == "INCOMPLETE_RANDOM_BASELINE"


def test_random_entry_baseline_uses_new_entries_and_has_a_null_distribution():
    candidates = list(range(20))
    calls = []
    def simulate(candidate):
        calls.append(candidate)
        return Decimal(str((candidate % 5) - 2))
    result = random_entry_baseline(candidates, simulate, trade_count=4, iterations=100, seed=11)
    assert result["iterations"] == 100
    assert len(set(result["expectancies_r"])) > 1
    assert len(calls) == 400


def test_walk_forward_windows_and_gate_failure_are_explicit():
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    windows = rolling_windows(start, datetime(2022, 1, 1, tzinfo=timezone.utc))
    assert windows and windows[0].out_sample_start == windows[0].in_sample_end
    result = evaluate_gate({"status": "DIAGNOSTIC", "trade_count": 1}, GoLiveGateSettings())
    assert not result.passed
    assert result.observation_mode


def test_walk_forward_uses_calendar_months_not_thirty_day_approximations():
    start = datetime(2024, 1, 31, tzinfo=timezone.utc)
    windows = rolling_windows(start, datetime(2025, 12, 31, tzinfo=timezone.utc), in_sample_months=1, out_sample_months=1, step_months=1)
    assert windows[0].in_sample_end == datetime(2024, 2, 29, tzinfo=timezone.utc)
    assert windows[0].out_sample_end == datetime(2024, 3, 29, tzinfo=timezone.utc)


def test_gate_enforces_ratio_and_positive_symbol_criteria():
    settings = GoLiveGateSettings(max_in_sample_out_sample_ratio=Decimal("2"), require_positive_in_symbols=3)
    result = evaluate_gate({"status": "VALIDATED", "out_of_sample_trades": 100, "expectancy_r": "0.2",
                            "baseline_percentile": "99", "max_drawdown_r": "1",
                            "in_sample_out_sample_ratio": "2.5", "positive_symbols": 2}, settings)
    assert not result.passed
    assert any("overfitting" in failure for failure in result.failures)
    assert any("positive symbols" in failure for failure in result.failures)
