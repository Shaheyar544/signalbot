from datetime import datetime, timezone
from decimal import Decimal

from app.backtest.gate import GoLiveGateSettings, evaluate_gate
from app.backtest.phase9_cli import build_parser, smoke_run_scope
from app.config.settings import load_settings


def test_smoke_scope_is_short_single_symbol_and_uses_small_iteration_counts():
    settings = load_settings("tests/fixtures/settings.yaml")
    end = datetime(2025, 2, 1, tzinfo=timezone.utc)
    sensitivity = {
        "left_bars": [2, 3, 4, 5],
        "right_bars": [2, 3, 4, 5],
    }

    scope = smoke_run_scope(settings, sensitivity, end=end)

    assert scope.symbols == ("ETHUSDT",)
    assert scope.start.isoformat() == "2025-01-02T00:00:00+00:00"
    assert scope.end == end
    assert scope.baseline_iterations == 20
    assert scope.monte_carlo_iterations == 20
    assert scope.sensitivity == {"left_bars": [2], "right_bars": [2]}
    assert "SMOKE_TEST" in scope.validation_label


def test_gate_rejects_smoke_test_label_even_when_every_numeric_criterion_passes():
    result = evaluate_gate({
        "status": "VALIDATED", "validation_label": "SMOKE_TEST:ETHUSDT",
        "out_of_sample_trades": 1000, "expectancy_r": Decimal("1"),
        "baseline_percentile": Decimal("100"), "max_drawdown_r": Decimal("0"),
        "in_sample_out_sample_ratio": Decimal("1"), "positive_symbols": 5,
    }, GoLiveGateSettings())

    assert not result.passed
    assert "smoke-test report cannot satisfy go-live gate" in result.failures


def test_cli_accepts_smoke_test_flag():
    assert build_parser().parse_args(["--smoke-test"]).smoke_test is True
