from datetime import datetime, timezone
from decimal import Decimal

from app.backtest.phase9 import run_random_entry_experiment, execute_walk_forward, run_sensitivity_sweep
from app.backtest.walkforward import WalkForwardWindow


def test_random_entry_experiment_samples_candidates_deterministically():
    candidates = tuple(range(10))
    result = run_random_entry_experiment(candidates, lambda value: Decimal(value - 4),
                                         trade_count=4, iterations=100, seed=9,
                                         observed_expectancy=Decimal("0"))
    again = run_random_entry_experiment(candidates, lambda value: Decimal(value - 4),
                                        trade_count=4, iterations=100, seed=9,
                                        observed_expectancy=Decimal("0"))
    assert result.expectancies_r == again.expectancies_r
    assert len(set(result.expectancies_r)) > 1
    assert result.iterations == 100
    assert result.p_value is not None


def test_walk_forward_executes_each_window_and_aggregates_oos():
    windows = (WalkForwardWindow(datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 7, 1, tzinfo=timezone.utc),
                                 datetime(2024, 7, 1, tzinfo=timezone.utc), datetime(2024, 9, 1, tzinfo=timezone.utc)),)
    calls = []
    def replay(window):
        calls.append(window)
        return (tuple([Decimal("1")]), tuple([Decimal("0.5"), Decimal("-0.25")]))
    result = execute_walk_forward(windows, replay)
    assert calls == list(windows)
    assert result.oos_trade_count == 2
    assert result.oos_total_r == Decimal("0.25")


def test_sensitivity_sweep_reports_all_values_without_selecting_one():
    result = run_sensitivity_sweep({"left_bars": (2, 3, 4)}, lambda name, value: Decimal(value) / Decimal(10))
    assert [point.value for point in result.points] == [Decimal(2), Decimal(3), Decimal(4)]
    assert result.plateau_width >= 1
    assert result.selected_value is None
