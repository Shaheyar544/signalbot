"""Go-live gate: failed validation always starts observation mode."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


@dataclass(frozen=True)
class GoLiveGateSettings:
    min_out_of_sample_trades: int = 100
    min_net_expectancy_r: Decimal = Decimal("0.10")
    max_in_sample_out_sample_ratio: Decimal = Decimal("2.0")
    min_baseline_percentile: Decimal = Decimal("95")
    max_drawdown_r: Decimal = Decimal("20")
    require_positive_in_symbols: int = 3
    report_max_age_days: int = 30


@dataclass(frozen=True)
class GateResult:
    passed: bool
    failures: tuple[str, ...]
    observation_mode: bool = True


def evaluate_gate(report: dict, settings: GoLiveGateSettings, *, now: datetime | None = None) -> GateResult:
    failures: list[str] = []
    label = str(report.get("validation_label", report.get("validation_scope", ""))).upper()
    if "SMOKE_TEST" in label:
        failures.append("smoke-test report cannot satisfy go-live gate")
    if report.get("status") not in {"VALIDATED", "COMPLETE"}:
        failures.append("validation report is not validated")
    if int(report.get("out_of_sample_trades", report.get("trade_count", 0))) < settings.min_out_of_sample_trades:
        failures.append("insufficient out-of-sample trades")
    if Decimal(str(report.get("expectancy_r", 0))) < settings.min_net_expectancy_r:
        failures.append("net expectancy below threshold")
    if Decimal(str(report.get("baseline_percentile", 0))) < settings.min_baseline_percentile:
        failures.append("random baseline percentile below threshold")
    if Decimal(str(report.get("max_drawdown_r", 0))) > settings.max_drawdown_r:
        failures.append("maximum drawdown exceeds threshold")
    ratio = report.get("in_sample_out_sample_ratio")
    if ratio is None:
        in_sample = report.get("in_sample_expectancy_r")
        out_sample = report.get("out_of_sample_expectancy_r")
        if in_sample is not None and out_sample is not None:
            denominator = abs(Decimal(str(out_sample)))
            ratio = Decimal("Infinity") if denominator == 0 else abs(Decimal(str(in_sample))) / denominator
    if ratio is not None and Decimal(str(ratio)) > settings.max_in_sample_out_sample_ratio:
        failures.append("in-sample/out-of-sample overfitting ratio exceeds threshold")
    elif ratio is None:
        failures.append("in-sample/out-of-sample ratio unavailable")
    positive_symbols = report.get("positive_symbols", report.get("positive_symbol_count"))
    if positive_symbols is not None and int(positive_symbols) < settings.require_positive_in_symbols:
        failures.append("positive symbols below threshold")
    elif positive_symbols is None:
        failures.append("positive symbol count unavailable")
    age = report.get("created_at")
    if age and now:
        created = datetime.fromisoformat(str(age))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if (now - created).days > settings.report_max_age_days:
            failures.append("validation report is too old")
    return GateResult(not failures, tuple(failures), bool(failures))
