from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.backtest.research import (
    LifecycleEvent,
    cost_stress_report,
    leave_one_symbol_out,
    lifecycle_funnel,
    monte_carlo_ordering,
    reproducibility_metadata,
    score_analytics,
)
from app.backtest.research_orchestrator import UnifiedResearchOrchestrator, write_research_outputs
from app.backtests import TradeAudit
from app.config.settings import load_settings


def trade(index: int, value: str, *, symbol: str = "ETHUSDT", score: str = "7", regime: str = "TREND_UP") -> TradeAudit:
    stamp = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(hours=index)
    return TradeAudit(str(index), "run", stamp, "BULLISH", Decimal("100"), Decimal("99"), Decimal("101"), Decimal("102"), Decimal("103"),
                      Decimal(score), "GOOD_SIGNAL", stamp + timedelta(hours=1), "TP1", Decimal(value), Decimal("0.1"), Decimal(value),
                      "TP_ONLY", False, index + 1, Decimal("1.2"), Decimal("-0.4"), symbol, regime, "US")


def test_score_analytics_has_fixed_score_bands_and_explicit_no_data():
    report = score_analytics([trade(0, "1", score="7"), trade(1, "-1", score="7"), trade(2, "2", score="9")])

    assert report["by_score"]["7"]["trade_count"] == 2
    assert report["by_score"]["7"]["median_r"] == Decimal("0")
    assert report["by_score"]["5"]["status"] == "NO_DATA"
    assert report["by_regime"]["TREND_UP"]["trade_count"] == 3


def test_monte_carlo_ordering_is_seed_deterministic_and_preserves_outcomes():
    trades = [trade(0, "1"), trade(1, "-2"), trade(2, "1"), trade(3, "-1")]
    first = monte_carlo_ordering(trades, iterations=100, random_seed=19, drawdown_threshold_r=Decimal("2"))
    again = monte_carlo_ordering(trades, iterations=100, random_seed=19, drawdown_threshold_r=Decimal("2"))

    assert first == again
    assert first["median_total_r"] == Decimal("-1")
    assert first["iterations"] == 100


def test_leave_one_symbol_out_includes_combined_and_each_configured_symbol():
    trades = [trade(0, "1", symbol="ETHUSDT"), trade(1, "-1", symbol="BTCUSDT"), trade(2, "2", symbol="SOLUSDT")]
    report = leave_one_symbol_out(trades, ("ETHUSDT", "BTCUSDT", "SOLUSDT"))

    assert report["combined"]["trade_count"] == 3
    assert report["exclude_ETHUSDT"]["trade_count"] == 2
    assert report["exclude_BTCUSDT"]["total_r"] == Decimal("3")


def test_cost_stress_is_explicit_and_never_mutates_base_settings():
    settings = load_settings("tests/fixtures/settings.yaml")
    audit = trade(0, "1")
    report = cost_stress_report([audit], settings)

    assert set(report) == {"BASE", "HIGH_SLIPPAGE", "HIGH_FEES", "ADVERSE_FUNDING", "SEVERE_COST"}
    assert report["SEVERE_COST"]["total_cost_r"] > report["BASE"]["total_cost_r"]
    assert settings.cost.slippage_percent == Decimal("0.02")


def test_lifecycle_funnel_uses_events_only_and_never_infers_absent_stages():
    events = [LifecycleEvent("CSD_DETECTED", "a"), LifecycleEvent("BREAKOUT_CONFIRMED", "a"), LifecycleEvent("CANCELLED", "a", "FAILED_RETEST")]
    report = lifecycle_funnel(events)

    assert report["stages"]["CSD_DETECTED"]["count"] == 1
    assert report["stages"]["SIGNAL_CONFIRMED"]["status"] == "NO_DATA"
    assert report["failure_reasons"]["FAILED_RETEST"] == 1


def test_reproducibility_metadata_is_stable_for_same_inputs(make_candle):
    settings = load_settings("tests/fixtures/settings.yaml")
    candles = [make_candle(symbol="ETHUSDT", offset=0), make_candle(symbol="ETHUSDT", offset=1)]
    first = reproducibility_metadata(settings, {"ETHUSDT": candles}, random_seed=7)
    again = reproducibility_metadata(settings, {"ETHUSDT": candles}, random_seed=7)

    assert first["research_run_id"] == again["research_run_id"]
    assert first["configuration_hash"] == again["configuration_hash"]


async def test_unified_research_pipeline_is_explicitly_incomplete_without_data(tmp_path):
    settings = load_settings("tests/fixtures/settings.yaml")
    report = await UnifiedResearchOrchestrator(settings, baseline_iterations=1, monte_carlo_iterations=2).run({"ETHUSDT": ()})
    json_path, csv_path = tmp_path / "report.json", tmp_path / "summary.csv"
    write_research_outputs(report, json_path=json_path, csv_path=csv_path)

    assert report["schema_version"] == "research-report-v1"
    assert report["go_live_gate"]["result"] == "FAIL"
    assert report["lifecycle_funnel"]["status"] == "UNAVAILABLE_NO_PERSISTED_LIFECYCLE_EVENTS"
    assert json_path.exists() and csv_path.exists()
