"""Unified, read-only research orchestration around the frozen V1 engine."""
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import csv
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Sequence

from app.backtest.gate import GoLiveGateSettings, evaluate_gate
from app.backtest.metrics import calculate_metrics
from app.backtest.data_integrity import check_integrity
from app.backtest.phase9 import Phase9ValidationOrchestrator, build_symbol_validation
from app.backtest.walkforward import rolling_windows
from app.backtest.research_cache import ResearchReplayCache, replay_cache_key
from app.backtest.research import (
    LifecycleEvent, cost_stress_report, leave_one_symbol_out, lifecycle_funnel,
    monte_carlo_ordering, reproducibility_metadata, score_analytics,
)
from app.config.settings import Settings
from app.events.models import Candle


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, tuple): return [_jsonable(item) for item in value]
    if isinstance(value, list): return [_jsonable(item) for item in value]
    if isinstance(value, dict): return {str(key): _jsonable(item) for key, item in value.items()}
    return value


class UnifiedResearchOrchestrator:
    """Composes existing validation seams; it never owns a strategy implementation."""
    def __init__(self, settings: Settings, *, baseline_iterations: int = 1000,
                 monte_carlo_iterations: int = 1000, random_seed: int = 7) -> None:
        self.settings = settings
        self.baseline_iterations = baseline_iterations
        self.monte_carlo_iterations = monte_carlo_iterations
        self.random_seed = random_seed
        self.cache = ResearchReplayCache()

    async def run(self, candles_by_symbol: dict[str, Sequence[Candle]], *,
                  sensitivity_dimensions: dict[str, Sequence[Any]] | None = None,
                  lifecycle_events: Sequence[LifecycleEvent] = ()) -> dict[str, Any]:
        timings: dict[str, float] = {}
        metadata = reproducibility_metadata(self.settings, candles_by_symbol, random_seed=self.random_seed)
        phase9 = Phase9ValidationOrchestrator(self.settings, baseline_iterations=self.baseline_iterations)
        started = perf_counter()
        per_symbol = {}
        for symbol, candles in candles_by_symbol.items():
            dates = [candle.open_time for candle in candles]
            key = replay_cache_key(git_commit=metadata["git_commit"], strategy_version=metadata["strategy_version"],
                                   configuration_hash=metadata["configuration_hash"], symbol=symbol,
                                   timeframes=tuple(self.settings.historical.timeframes),
                                   start=min(dates).isoformat() if dates else None, end=max(dates).isoformat() if dates else None,
                                   variant="canonical-baseline")
            async def compute(candles=candles):
                return await build_symbol_validation(self.settings, candles, baseline_iterations=self.baseline_iterations)
            per_symbol[symbol] = await self.cache.get_or_compute_async(key, compute)
        timings["baseline_replay_seconds"] = perf_counter() - started
        audits = [audit for result in per_symbol.values() for audit in result["audits"]]
        ordered_times = [candle.open_time for candles in candles_by_symbol.values() for candle in candles]
        windows = rolling_windows(min(ordered_times), max(ordered_times)) if ordered_times else ()
        started = perf_counter()
        walk = await phase9._walk_forward(candles_by_symbol, windows)
        timings["walk_forward_seconds"] = perf_counter() - started
        started = perf_counter()
        sensitivity = await phase9._sensitivity(candles_by_symbol, sensitivity_dimensions) if sensitivity_dimensions else None
        timings["sensitivity_seconds"] = perf_counter() - started
        complete = bool(windows and sensitivity is not None and not sensitivity.unsupported_parameters and
                        all(result["baseline"] is not None for result in per_symbol.values()))
        started = perf_counter()
        htf = await self._htf_experiment(candles_by_symbol)
        timings["htf_experiment_seconds"] = perf_counter() - started
        baseline_percentiles = [result["baseline"].percentile for result in per_symbol.values() if result["baseline"]]
        positive_symbols = sum(result["metrics"].expectancy_r > 0 for result in per_symbol.values())
        gate_input = {
            "status": "VALIDATED" if complete else "INCOMPLETE_VALIDATION_ORCHESTRATION",
            "out_of_sample_trades": walk.oos_trade_count,
            "expectancy_r": walk.oos_expectancy_r,
            "baseline_percentile": min(baseline_percentiles) if baseline_percentiles else Decimal(0),
            "max_drawdown_r": calculate_metrics(audits).max_drawdown_r,
            "positive_symbols": positive_symbols,
            "created_at": metadata["run_timestamp"],
        }
        gate = evaluate_gate(gate_input, GoLiveGateSettings(**(self.settings.go_live_gate or {})))
        lifecycle = lifecycle_funnel(lifecycle_events)
        integrity = self._data_integrity(candles_by_symbol)
        started = perf_counter()
        monte_carlo = monte_carlo_ordering(audits, iterations=self.monte_carlo_iterations, random_seed=self.random_seed)
        timings["monte_carlo_seconds"] = perf_counter() - started
        started = perf_counter()
        leave_one_out = leave_one_symbol_out(audits, self.settings.historical.symbols)
        cost_stress = cost_stress_report(audits, self.settings)
        timings["aggregation_seconds"] = perf_counter() - started
        methodology = {**metadata, "analysis_scopes": {
            "strategy_performance": "canonical strategy, exit, and cost audit metrics",
            "sequence_risk_monte_carlo": "trade-order permutations only; not evidence of strategy edge",
            "sensitivity": "owner-supplied observations; no parameter selection",
            "oos_validation": "calendar walk-forward chronological output",
            "lifecycle": "persisted entity-linked events only",
            "cost_stress": "existing CostModel repricing with explicit scenarios",
        }}
        return {
            "schema_version": "research-report-v1",
            "research_run_id": metadata["research_run_id"],
            "status": "READY_FOR_HUMAN_REVIEW" if complete else "INCOMPLETE_VALIDATION",
            "methodology": methodology,
            "baseline": {symbol: asdict(result["baseline"]) if result["baseline"] else {"status": "NO_ELIGIBLE_ENTRIES"}
                         for symbol, result in per_symbol.items()},
            "score_analysis": score_analytics(audits),
            "htf_experiment": htf,
            "walk_forward": asdict(walk),
            "sensitivity": asdict(sensitivity) if sensitivity else {"status": "INCOMPLETE_SENSITIVITY_CONFIGURATION"},
            "monte_carlo": monte_carlo,
            "leave_one_symbol_out": leave_one_out,
            "cost_stress": cost_stress,
            "lifecycle_funnel": lifecycle,
            "data_integrity": integrity,
            "go_live_gate": {"result": "PASS" if gate.passed else "FAIL", "failures": list(gate.failures),
                             "observation_mode": gate.observation_mode, "input": gate_input},
            "performance": {"timings_seconds": timings, "replay_count": {
                "baseline": len(per_symbol), "walk_forward": len(windows) * len(candles_by_symbol),
                "sensitivity": sum(len(values) for values in (sensitivity_dimensions or {}).values()) * len(candles_by_symbol),
                "htf": 3 * len(candles_by_symbol), "total": len(per_symbol) + len(windows) * len(candles_by_symbol) + sum(len(values) for values in (sensitivity_dimensions or {}).values()) * len(candles_by_symbol) + 3 * len(candles_by_symbol)},
                            "cache": self.cache.stats, "candles_processed_input": sum(len(candles) for candles in candles_by_symbol.values())},
        }

    def _data_integrity(self, candles_by_symbol: dict[str, Sequence[Candle]]) -> dict[str, Any]:
        expected_symbols = tuple(self.settings.historical.symbols)
        missing_symbols = [symbol for symbol in expected_symbols if symbol not in candles_by_symbol]
        reports: dict[str, Any] = {}
        incomplete = bool(missing_symbols)
        for symbol in expected_symbols:
            for timeframe in self.settings.historical.timeframes:
                candles = [candle for candle in candles_by_symbol.get(symbol, ()) if candle.timeframe == timeframe]
                check = check_integrity(symbol, timeframe, candles)
                status = "OK" if check.is_clean else "INCOMPLETE_DATA"
                incomplete = incomplete or status != "OK"
                reports[f"{symbol}:{timeframe}"] = {
                    "status": status, "candle_count": check.candle_count,
                    "range_start": check.range_start.isoformat() if check.range_start else None,
                    "range_end": check.range_end.isoformat() if check.range_end else None,
                    "gap_count": len(check.gaps), "missing_candles": sum(gap.missing_candles for gap in check.gaps),
                    "duplicate_open_times": check.duplicate_open_times, "ohlc_violations": check.ohlc_violations,
                }
        return {"status": "INCOMPLETE_DATA" if incomplete else "OK", "missing_symbols": missing_symbols, "series": reports}

    async def _htf_experiment(self, candles_by_symbol: dict[str, Sequence[Candle]]) -> dict[str, Any]:
        variants = {
            "15M_ONLY": (self.settings.primary_timeframe,),
            "15M_1H": (self.settings.primary_timeframe, "1h"),
            "15M_1H_4H": (self.settings.primary_timeframe, "1h", "4h"),
        }
        result: dict[str, Any] = {}
        for name, timeframes in variants.items():
            audits = []
            for candles in candles_by_symbol.values():
                subset = [candle for candle in candles if candle.timeframe in timeframes]
                validation = await build_symbol_validation(self.settings, subset, baseline_iterations=1, include_baseline=False)
                audits.extend(validation["audits"])
            result[name] = {**_metrics_summary(audits),
                            "timeframes": list(timeframes), "canonical_cost_exit_engine": True}
        return result


def _metrics_summary(audits):
    metrics = calculate_metrics(audits)
    return {"trade_count": metrics.trade_count, "win_rate": metrics.win_rate,
            "expectancy_r": metrics.expectancy_r, "average_r": metrics.expectancy_r,
            "profit_factor": metrics.profit_factor, "max_drawdown_r": metrics.max_drawdown_r,
            "total_r": metrics.total_r}


def write_research_outputs(report: dict[str, Any], *, json_path: str | Path, csv_path: str | Path | None = None) -> None:
    """Persist a versioned JSON report and a concise top-level CSV summary."""
    destination = Path(json_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(_jsonable(report), indent=2, sort_keys=True), encoding="utf-8")
    if csv_path is not None:
        output = Path(csv_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=("scope", "trade_count", "expectancy_r", "total_r", "max_drawdown_r", "profit_factor"))
            writer.writeheader()
            for scope, values in report["leave_one_symbol_out"].items():
                writer.writerow({"scope": scope, **{name: values.get(name) for name in writer.fieldnames[1:]}})
