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
    age = report.get("created_at")
    if age and now:
        created = datetime.fromisoformat(str(age))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if (now - created).days > settings.report_max_age_days:
            failures.append("validation report is too old")
    return GateResult(not failures, tuple(failures), bool(failures))
