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
    _percentile,
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
    assert first["total_r_is_invariant"] is True
    assert "probability_ending_negative" not in first


def test_monte_carlo_ordering_changes_sequence_risk_but_not_total_r():
    values = [Decimal("1"), Decimal("-2"), Decimal("1"), Decimal("-1")]
    assert sum(values) == sum(reversed(values))
    report = monte_carlo_ordering([trade(index, str(value)) for index, value in enumerate(values)], iterations=30, random_seed=3)
    assert report["p95_max_drawdown_r"] >= Decimal("2")


def test_leave_one_symbol_out_includes_combined_and_each_configured_symbol():
    trades = [trade(0, "1", symbol="ETHUSDT"), trade(1, "-1", symbol="BTCUSDT"), trade(2, "2", symbol="SOLUSDT")]
    report = leave_one_symbol_out(trades, ("ETHUSDT", "BTCUSDT", "SOLUSDT"))

    assert report["combined"]["trade_count"] == 3
    assert report["exclude_ETHUSDT"]["trade_count"] == 2
    assert report["exclude_BTCUSDT"]["total_r"] == Decimal("3")


def test_cost_stress_is_explicit_and_never_mutates_base_settings():
    settings = load_settings("tests/fixtures/settings.yaml")
    stamp = datetime(2025, 1, 1, tzinfo=timezone.utc)
    audit = replace(trade(0, "1"), entry_time=stamp, exit_time=stamp + timedelta(hours=1), exit_price=Decimal("101"))
    report = cost_stress_report([audit], settings)

    assert set(report) == {"BASE", "HIGH_SLIPPAGE", "HIGH_FEES", "ADVERSE_FUNDING", "SEVERE_COST"}
    assert report["SEVERE_COST"]["total_cost_r"] > report["BASE"]["total_cost_r"]
    assert settings.cost.slippage_percent == Decimal("0.02")


def test_cost_stress_requires_actual_fill_timestamps_and_exit_price_and_uses_them():
    settings = load_settings("tests/fixtures/settings.yaml")
    opened = datetime(2025, 1, 1, tzinfo=timezone.utc)
    tp2 = replace(trade(0, "2"), entry_time=opened, exit_time=opened + timedelta(hours=9),
                  exit_price=Decimal("102"), take_profit_1=Decimal("101"), exit_reason="TP2")
    stop = replace(trade(1, "-1"), entry_time=opened, exit_time=opened + timedelta(hours=9),
                   exit_price=Decimal("99"), exit_reason="SL")
    time_stop = replace(trade(2, "0.3"), entry_time=opened, exit_time=opened + timedelta(hours=9),
                        exit_price=Decimal("100.3"), exit_reason="TIME_STOP")
    report = cost_stress_report([tp2, stop, time_stop], settings)

    assert report["BASE"]["status"] == "OK"
    assert report["BASE"]["total_cost_r"] > Decimal("0")


def test_cost_stress_passes_the_recorded_exit_price_to_cost_model(monkeypatch):
    from app.backtest.costs import CostBreakdown, CostModel
    captured = []
    original = CostModel.breakdown
    def capture(self, **kwargs):
        captured.append((kwargs["exit_price"], kwargs["is_stop_exit"], kwargs["opened_at"], kwargs["closed_at"]))
        return original(self, **kwargs)
    monkeypatch.setattr(CostModel, "breakdown", capture)
    opened = datetime(2025, 1, 1, tzinfo=timezone.utc)
    records = [
        replace(trade(0, "2"), entry_time=opened, exit_time=opened + timedelta(hours=1), exit_price=Decimal("102"), exit_reason="TP2"),
        replace(trade(1, "-1"), entry_time=opened, exit_time=opened + timedelta(hours=2), exit_price=Decimal("99"), exit_reason="SL"),
        replace(trade(2, "0"), entry_time=opened, exit_time=opened + timedelta(hours=3), exit_price=Decimal("100.3"), exit_reason="TIME_STOP"),
    ]
    cost_stress_report(records, load_settings("tests/fixtures/settings.yaml"))

    # Five scenarios each process the original actual recorded exits.
    assert (Decimal("102"), False, opened, opened + timedelta(hours=1)) in captured
    assert (Decimal("99"), True, opened, opened + timedelta(hours=2)) in captured
    assert (Decimal("100.3"), False, opened, opened + timedelta(hours=3)) in captured


def test_cost_stress_marks_old_audits_without_actual_execution_data_incomplete():
    report = cost_stress_report([trade(0, "1")], load_settings("tests/fixtures/settings.yaml"))
    assert report["BASE"]["status"] == "INCOMPLETE_DATA"


def test_lifecycle_funnel_uses_entity_aware_sequential_conversion_and_terminal_outcomes():
    events = [LifecycleEvent("CSD_DETECTED", "a"), LifecycleEvent("BREAKOUT_CONFIRMED", "a"),
              LifecycleEvent("WAITING_FOR_RETEST", "a"), LifecycleEvent("RETEST_DETECTED", "a"),
              LifecycleEvent("CONFIRMATION_PENDING", "a"), LifecycleEvent("SIGNAL_CONFIRMED", "a"), LifecycleEvent("TP1", "a"),
              LifecycleEvent("CSD_DETECTED", "b"), LifecycleEvent("CANCELLED", "b", "FAILED_RETEST")]
    report = lifecycle_funnel(events)

    assert report["status"] == "OK"
    assert report["stages"]["CSD_DETECTED"]["count"] == 2
    assert report["stages"]["SIGNAL_CONFIRMED"]["count"] == 1
    assert report["terminal_outcomes"]["CANCELLED"] == 1
    assert report["failure_reasons"]["FAILED_RETEST"] == 1


def test_lifecycle_funnel_refuses_unlinked_stage_events():
    report = lifecycle_funnel([LifecycleEvent("RETEST_DETECTED", "orphan")])
    assert report["status"] == "UNAVAILABLE_INSUFFICIENT_LIFECYCLE_LINKAGE"


def test_score_analytics_uses_persisted_htf_and_component_evidence_only():
    enriched = replace(trade(0, "1"), htf_agreement={"1h": True, "4h": False},
                       confirmation_ema=True, confirmation_rsi=False, confirmation_macd=True,
                       confirmation_volume=False, setup_csd=True, setup_breakout=True, setup_retest=True)
    report = score_analytics([enriched])
    assert report["by_htf_agreement"]["NOT_FULLY_AGREE"]["trade_count"] == 1
    assert report["by_confirmation_component"]["ema"]["TRUE"]["trade_count"] == 1


def test_reproducibility_metadata_is_stable_for_same_inputs(make_candle):
    settings = load_settings("tests/fixtures/settings.yaml")
    candles = [make_candle(symbol="ETHUSDT", offset=0), make_candle(symbol="ETHUSDT", offset=1)]
    first = reproducibility_metadata(settings, {"ETHUSDT": candles}, random_seed=7, git_commit="a")
    again = reproducibility_metadata(settings, {"ETHUSDT": candles}, random_seed=7, git_commit="a")

    assert first["research_run_id"] == again["research_run_id"]
    assert first["configuration_hash"] == again["configuration_hash"]
    assert reproducibility_metadata(settings, {"ETHUSDT": candles}, random_seed=7, git_commit="b")["research_run_id"] != first["research_run_id"]
    assert reproducibility_metadata(settings, {"ETHUSDT": candles}, random_seed=8, git_commit="a")["research_run_id"] != first["research_run_id"]
    assert reproducibility_metadata(replace(settings, historical_candle_limit=99), {"ETHUSDT": candles}, random_seed=7, git_commit="a")["research_run_id"] != first["research_run_id"]


def test_percentile_uses_nearest_rank_convention():
    assert _percentile([Decimal("5")], Decimal(95)) == Decimal("5")
    assert _percentile([Decimal("1"), Decimal("2")], Decimal(90)) == Decimal("2")
    assert _percentile([Decimal("1"), Decimal("2"), Decimal("3")], Decimal(50)) == Decimal("2")
    assert _percentile([Decimal(index) for index in range(1, 101)], Decimal(90)) == Decimal("90")


async def test_unified_research_pipeline_is_explicitly_incomplete_without_data(tmp_path):
    settings = load_settings("tests/fixtures/settings.yaml")
    report = await UnifiedResearchOrchestrator(settings, baseline_iterations=1, monte_carlo_iterations=2).run({"ETHUSDT": ()})
    json_path, csv_path = tmp_path / "report.json", tmp_path / "summary.csv"
    write_research_outputs(report, json_path=json_path, csv_path=csv_path)

    assert report["schema_version"] == "research-report-v1"
    assert report["go_live_gate"]["result"] == "FAIL"
    assert report["lifecycle_funnel"]["status"] == "UNAVAILABLE_INSUFFICIENT_LIFECYCLE_LINKAGE"
    assert report["data_integrity"]["status"] == "INCOMPLETE_DATA"
    assert json_path.exists() and csv_path.exists()
