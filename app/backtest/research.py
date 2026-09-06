"""Pure research-report calculations over canonical persisted trade audits.

Nothing here creates a strategy signal or changes a production setting.  Each
experiment accepts immutable audits/settings produced by the existing canonical
strategy, exit, and cost seams.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from hashlib import sha256
import json
from pathlib import Path
import random
import subprocess
from typing import Any, Iterable, Sequence

from app.backtest.costs import CostModel
from app.backtest.metrics import calculate_metrics
from app.backtests import TradeAudit
from app.config.settings import CostSettings, Settings
from app.structure.csd import CSDDirection


SCORE_BANDS = tuple(range(5, 11))
LIFECYCLE_STAGES = (
    "CSD_DETECTED", "BREAKOUT_CONFIRMED", "WAITING_FOR_RETEST", "RETEST_DETECTED",
    "CONFIRMATION_PENDING", "SIGNAL_CONFIRMED", "TP1", "TP2", "TP3", "TP4", "SL",
    "TIME_STOP", "CANCELLED", "INVALIDATED", "BREAKOUT_FAILED", "RETEST_FAILED",
)


@dataclass(frozen=True)
class LifecycleEvent:
    stage: str
    entity_id: str
    failure_reason: str | None = None
    occurred_at: datetime | None = None


def _median(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    return ordered[midpoint] if len(ordered) % 2 else (ordered[midpoint - 1] + ordered[midpoint]) / Decimal(2)


def _summary(trades: Sequence[TradeAudit]) -> dict[str, Any]:
    if not trades:
        return {"status": "NO_DATA", "trade_count": 0, "win_rate": None, "average_r": None,
                "median_r": None, "expectancy_r": None, "profit_factor": None,
                "max_drawdown_r": None, "total_r": None, "gross_r": None,
                "total_cost_r": None, "average_holding_bars": None}
    metrics = calculate_metrics(trades)
    values = [trade.net_r for trade in trades if trade.net_r is not None]
    return {
        "status": "OK" if values else "INCOMPLETE_DATA",
        "trade_count": metrics.trade_count,
        "win_rate": metrics.win_rate,
        "average_r": metrics.expectancy_r,
        "median_r": _median(values),
        "expectancy_r": metrics.expectancy_r,
        "profit_factor": metrics.profit_factor,
        "profit_factor_status": metrics.profit_factor_status,
        "max_drawdown_r": metrics.max_drawdown_r,
        "total_r": metrics.total_r,
        "gross_r": metrics.gross_r,
        "total_cost_r": metrics.total_cost_r,
        "average_holding_bars": metrics.average_bars_in_trade,
    }


def _group(trades: Sequence[TradeAudit], key) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[TradeAudit]] = {}
    for trade in trades:
        groups.setdefault(str(key(trade)), []).append(trade)
    return {name: _summary(items) for name, items in sorted(groups.items())}


def score_analytics(trades: Sequence[TradeAudit]) -> dict[str, Any]:
    """Measure frozen scoring; bands use score floor (e.g. 7.0–7.999 => 7)."""
    by_score: dict[str, dict[str, Any]] = {}
    for band in SCORE_BANDS:
        items = [trade for trade in trades if int(trade.score_total) == band]
        by_score[str(band)] = _summary(items)
    fields = {
        "ema": "confirmation_ema", "rsi": "confirmation_rsi", "macd": "confirmation_macd",
        "volume": "confirmation_volume", "csd": "setup_csd", "breakout": "setup_breakout", "retest": "setup_retest",
    }
    component_data = {
        name: _group([trade for trade in trades if getattr(trade, field) is not None], lambda trade, field=field: "TRUE" if getattr(trade, field) else "FALSE")
        for name, field in fields.items()
    }
    htf_trades = [trade for trade in trades if trade.htf_one_hour is not None and trade.htf_four_hour is not None]
    return {
        "band_definition": "floor(score_total), restricted to 5..10",
        "by_score": by_score,
        "by_direction": _group(trades, lambda trade: trade.direction),
        "by_symbol": _group(trades, lambda trade: trade.symbol or "UNKNOWN"),
        "by_regime": _group(trades, lambda trade: trade.regime or "UNAVAILABLE"),
        "by_htf_agreement": _group(htf_trades, lambda trade: "AGREES" if trade.htf_one_hour and trade.htf_four_hour else "NOT_FULLY_AGREE")
        if htf_trades else {"status": "UNAVAILABLE_NOT_PERSISTED"},
        "by_confirmation_component": component_data if any(component_data.values()) else {"status": "UNAVAILABLE_NOT_PERSISTED"},
    }


def _drawdown_and_streak(values: Sequence[Decimal]) -> tuple[Decimal, int]:
    equity = peak = Decimal(0)
    drawdown = Decimal(0)
    streak = longest = 0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
        if value <= 0:
            streak += 1
            longest = max(longest, streak)
        else:
            streak = 0
    return drawdown, longest


def _percentile(values: Sequence[Decimal], percentile: Decimal) -> Decimal | None:
    """Nearest-rank percentile: rank=ceil(p/100*n), 1-indexed."""
    if not values:
        return None
    if not Decimal(0) <= percentile <= Decimal(100):
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(values)
    rank = (percentile * Decimal(len(ordered)) / Decimal(100)).to_integral_value(rounding=ROUND_CEILING)
    index = max(0, min(len(ordered) - 1, int(rank) - 1))
    return ordered[index]


def monte_carlo_ordering(trades: Sequence[TradeAudit], *, iterations: int = 1000,
                         random_seed: int = 7, drawdown_threshold_r: Decimal = Decimal("20")) -> dict[str, Any]:
    """Shuffle completed net outcomes only; this tests sequence risk, not entry edge."""
    if iterations < 1:
        raise ValueError("iterations must be positive")
    outcomes = [trade.net_r for trade in trades if trade.net_r is not None]
    if not outcomes:
        return {"status": "NO_DATA", "iterations": iterations, "random_seed": random_seed}
    rng = random.Random(random_seed)
    totals: list[Decimal] = []
    drawdowns: list[Decimal] = []
    streaks: list[Decimal] = []
    for _ in range(iterations):
        sample = list(outcomes)
        rng.shuffle(sample)
        drawdown, streak = _drawdown_and_streak(sample)
        totals.append(sum(sample, Decimal(0)))
        drawdowns.append(drawdown)
        streaks.append(Decimal(streak))
    return {
        "status": "OK", "iterations": iterations, "random_seed": random_seed,
        "drawdown_threshold_r": drawdown_threshold_r,
        "median_total_r": _median(totals), "median_max_drawdown_r": _median(drawdowns),
        "p90_max_drawdown_r": _percentile(drawdowns, Decimal(90)),
        "p95_max_drawdown_r": _percentile(drawdowns, Decimal(95)),
        "p99_max_drawdown_r": _percentile(drawdowns, Decimal(99)),
        "median_max_losing_streak": _median(streaks),
        "p95_max_losing_streak": _percentile(streaks, Decimal(95)),
        "total_r_is_invariant": True,
        "invariant_total_r": totals[0],
        "probability_drawdown_exceeds_threshold": Decimal(sum(value > drawdown_threshold_r for value in drawdowns)) / Decimal(iterations),
    }


def leave_one_symbol_out(trades: Sequence[TradeAudit], symbols: Sequence[str]) -> dict[str, dict[str, Any]]:
    result = {"combined": _summary(trades)}
    for symbol in symbols:
        result[f"exclude_{symbol}"] = _summary([trade for trade in trades if trade.symbol != symbol])
    return result


def _stress_settings(base: CostSettings) -> dict[str, CostSettings]:
    return {
        "BASE": base,
        "HIGH_SLIPPAGE": replace(base, slippage_percent=base.slippage_percent * 2,
                                  slippage_percent_stop=base.slippage_percent_stop * 2),
        "HIGH_FEES": replace(base, taker_fee_percent=base.taker_fee_percent * 2,
                             maker_fee_percent=base.maker_fee_percent * 2),
        "ADVERSE_FUNDING": replace(base, funding_rate_source="fixed",
                                    funding_rate_fixed_percent=max(base.funding_rate_fixed_percent * 3, Decimal("0.01"))),
        "SEVERE_COST": replace(base, taker_fee_percent=base.taker_fee_percent * 2,
                               maker_fee_percent=base.maker_fee_percent * 2,
                               slippage_percent=base.slippage_percent * 3,
                               slippage_percent_stop=base.slippage_percent_stop * 3,
                               funding_rate_source="fixed",
                               funding_rate_fixed_percent=max(base.funding_rate_fixed_percent * 3, Decimal("0.01"))),
    }


def cost_stress_report(trades: Sequence[TradeAudit], settings: Settings) -> dict[str, dict[str, Any]]:
    """Reprice audit costs through the existing CostModel, never mutate settings."""
    report: dict[str, dict[str, Any]] = {}
    for name, cost_settings in _stress_settings(settings.cost).items():
        model = CostModel(cost_settings)
        stressed: list[TradeAudit] = []
        missing_execution_data = 0
        for trade in trades:
            if None in (trade.entry_price, trade.stop_loss, trade.entry_time, trade.exit_time,
                        trade.exit_price, trade.exit_reason, trade.gross_r):
                missing_execution_data += 1
                continue
            breakdown = model.breakdown(direction=CSDDirection(trade.direction), entry=trade.entry_price,
                                        stop_loss=trade.stop_loss, exit_price=trade.exit_price,
                                        is_stop_exit=trade.exit_reason in {"SL", "STOP_AFTER_PARTIAL_TP"}, opened_at=trade.entry_time,
                                        closed_at=trade.exit_time)
            stressed.append(replace(trade, costs_r=breakdown.total_r, net_r=trade.gross_r - breakdown.total_r))
        status = "INCOMPLETE_DATA" if missing_execution_data else _summary(stressed)["status"]
        report[name] = {**_summary(stressed), "status": status, "missing_execution_records": missing_execution_data,
                        "assumptions": asdict(cost_settings)}
    return report


def lifecycle_funnel(events: Iterable[LifecycleEvent]) -> dict[str, Any]:
    """Build a funnel only from valid, entity-linked event sequences."""
    event_list = tuple(events)
    sequential = ("CSD_DETECTED", "BREAKOUT_CONFIRMED", "WAITING_FOR_RETEST", "RETEST_DETECTED",
                  "CONFIRMATION_PENDING", "SIGNAL_CONFIRMED")
    terminals = tuple(stage for stage in LIFECYCLE_STAGES if stage not in sequential)
    if not event_list or any(not event.entity_id or event.stage not in LIFECYCLE_STAGES for event in event_list):
        return {"status": "UNAVAILABLE_INSUFFICIENT_LIFECYCLE_LINKAGE", "source": "persisted lifecycle events only",
                "stages": {}, "terminal_outcomes": {}, "failure_reasons": {}}
    by_entity: dict[str, list[LifecycleEvent]] = {}
    for event in event_list:
        by_entity.setdefault(event.entity_id, []).append(event)
    reached = {stage: set() for stage in sequential}
    invalid_linkage = False
    terminal_outcomes = {stage: set() for stage in terminals}
    for entity, entity_events in by_entity.items():
        seen = {event.stage for event in entity_events}
        for stage in terminals:
            if stage in seen:
                terminal_outcomes[stage].add(entity)
        previous_seen = True
        for stage in sequential:
            if stage in seen:
                if not previous_seen:
                    invalid_linkage = True
                else:
                    reached[stage].add(entity)
            else:
                previous_seen = False
    if invalid_linkage:
        return {"status": "UNAVAILABLE_INSUFFICIENT_LIFECYCLE_LINKAGE", "source": "persisted lifecycle events only",
                "stages": {}, "terminal_outcomes": {stage: len(items) for stage, items in terminal_outcomes.items()},
                "failure_reasons": {}}
    stages: dict[str, dict[str, Any]] = {}
    previous: int | None = None
    for stage in sequential:
        count = len(reached[stage])
        stages[stage] = {
            "status": "OK" if count else "NO_DATA",
            "count": count,
            "conversion_from_previous": None if previous is None or previous == 0 else Decimal(count) / Decimal(previous),
        }
        previous = count
    failures = {stage: len(terminal_outcomes[stage]) for stage in ("CANCELLED", "INVALIDATED", "BREAKOUT_FAILED", "RETEST_FAILED")}
    return {"status": "OK", "source": "persisted lifecycle events only", "stages": stages,
            "terminal_outcomes": {stage: len(items) for stage, items in terminal_outcomes.items()},
            "failure_percentage": Decimal(sum(failures.values())) / Decimal(len(by_entity)) if by_entity else None,
            "failure_reasons": {reason: sum(event.failure_reason == reason for event in event_list)
                                for reason in sorted({event.failure_reason for event in event_list if event.failure_reason})}}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, datetime): return value.isoformat()
    if isinstance(value, Path): return str(value)
    if isinstance(value, tuple): return [_jsonable(item) for item in value]
    if isinstance(value, list): return [_jsonable(item) for item in value]
    if isinstance(value, dict): return {str(key): _jsonable(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    return value


def reproducibility_metadata(settings: Settings, candles_by_symbol: dict[str, Sequence[Any]], *, random_seed: int,
                            strategy_version: str = "V1_FROZEN", methodology_id: str = "signalbot-research-v1",
                            git_commit: str | None = None, validation_label: str | None = None) -> dict[str, Any]:
    snapshot = _jsonable(asdict(settings))
    configuration_hash = sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    dates = [candle.open_time for candles in candles_by_symbol.values() for candle in candles]
    if git_commit is None:
        try:
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            commit = "UNAVAILABLE"
    else:
        commit = git_commit
    identity = {"configuration_hash": configuration_hash, "symbols": sorted(candles_by_symbol),
                "start": min(dates).isoformat() if dates else None, "end": max(dates).isoformat() if dates else None,
                "timeframes": list(settings.timeframes), "random_seed": random_seed, "strategy_version": strategy_version,
                "methodology_id": methodology_id, "git_commit": commit, "cost_assumptions": _jsonable(asdict(settings.cost)),
                "exit_policy": _jsonable(asdict(settings.exit_policy)), "validation_label": validation_label}
    research_run_id = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:24]
    return {"research_run_id": research_run_id, "git_commit": commit, "strategy_version": strategy_version,
            "methodology_id": methodology_id, "configuration_hash": configuration_hash,
            "configuration_snapshot": snapshot, "symbols": identity["symbols"],
            "timeframes": list(settings.timeframes), "historical_date_range": {"start": identity["start"], "end": identity["end"]},
            "cost_assumptions": _jsonable(asdict(settings.cost)), "exit_policy": _jsonable(asdict(settings.exit_policy)),
            "random_seed": random_seed, "validation_label": validation_label,
            "run_timestamp": datetime.now(timezone.utc).isoformat()}
