"""Unified, read-only research orchestration around the frozen V1 engine."""
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import asyncio
from concurrent.futures import Executor, ProcessPoolExecutor
import csv
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any, Sequence
import hashlib

from app.backtest.gate import GoLiveGateSettings, evaluate_gate
from app.backtest.metrics import calculate_metrics
from app.backtest.data_integrity import check_integrity
from app.backtest.phase9 import (Phase9ValidationOrchestrator, SensitivityPoint, SensitivityResult,
                                 WalkForwardResult, _replace_frozen_setting, build_symbol_validation)
from app.backtest.walkforward import rolling_windows
from app.backtest.research_cache import ResearchReplayCache, replay_cache_key
from app.backtest.research import (
    LifecycleEvent, cost_stress_report, leave_one_symbol_out, lifecycle_funnel,
    monte_carlo_ordering, reproducibility_metadata, score_analytics,
)
from app.config.settings import Settings
from app.events.models import Candle
from app.backtest.research_checkpoints import ResearchCheckpointStore, ResearchProgress, atomic_json_write, jsonable


def _run_symbol_validation_sync(settings: Settings, candles: Sequence[Candle], baseline_iterations: int) -> dict[str, Any]:
    """Picklable canonical replay wrapper for an isolated symbol worker."""
    return asyncio.run(build_symbol_validation(settings, candles, baseline_iterations=baseline_iterations))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, tuple): return [_jsonable(item) for item in value]
    if isinstance(value, list): return [_jsonable(item) for item in value]
    if isinstance(value, dict): return {str(key): _jsonable(item) for key, item in value.items()}
    return value


class UnifiedResearchOrchestrator:
    """Composes existing validation seams; it never owns a strategy implementation."""
    def __init__(self, settings: Settings, *, baseline_iterations: int = 1000,
                 monte_carlo_iterations: int = 1000, random_seed: int = 7,
                 max_workers: int | None = None,
                 executor_factory: Any = ProcessPoolExecutor) -> None:
        self.settings = settings
        self.baseline_iterations = baseline_iterations
        self.monte_carlo_iterations = monte_carlo_iterations
        self.random_seed = random_seed
        if max_workers is not None and max_workers < 1:
            raise ValueError("max_workers must be positive")
        self.max_workers = max_workers
        self.executor_factory = executor_factory
        self.cache = ResearchReplayCache()

    async def run(self, candles_by_symbol: dict[str, Sequence[Candle]], *,
                  sensitivity_dimensions: dict[str, Sequence[Any]] | None = None,
                  lifecycle_events: Sequence[LifecycleEvent] = (),
                  checkpoint_root: str | Path | None = None,
                  progress_path: str | Path | None = None,
                  partial_report_path: str | Path | None = None,
                  checkpoint_mode: str = "fresh",
                  validation_label: str | None = None) -> dict[str, Any]:
        timings: dict[str, float] = {}
        metadata = reproducibility_metadata(self.settings, candles_by_symbol, random_seed=self.random_seed,
                                            validation_label=validation_label)
        dataset_identity = _dataset_identity(candles_by_symbol)
        checkpoint_identity = {key: metadata[key] for key in ("research_run_id", "git_commit", "configuration_hash", "methodology_id", "random_seed", "validation_label")}
        checkpoint_identity["dataset_identity"] = dataset_identity
        checkpoint_store = ResearchCheckpointStore(checkpoint_root, checkpoint_identity, mode=checkpoint_mode) if checkpoint_root else None
        sensitivity_units = sum(len(values) for values in (sensitivity_dimensions or {}).values())
        unit_total = len(candles_by_symbol) + (len(candles_by_symbol) * len(rolling_windows(min((c.open_time for values in candles_by_symbol.values() for c in values), default=None), max((c.open_time for values in candles_by_symbol.values() for c in values), default=None))) if any(candles_by_symbol.values()) else 0) + sensitivity_units + (3 * len(candles_by_symbol)) + 3
        progress = ResearchProgress(progress_path, checkpoint_identity, unit_total) if progress_path else None
        completed_units = 0
        partial: dict[str, Any] = {"schema_version": "research-report-v1", "research_run_id": metadata["research_run_id"],
                                   "status": "RUNNING", "methodology": {**metadata, "dataset_identity": dataset_identity}}
        def update(phase: str, item: str) -> None:
            nonlocal completed_units
            completed_units += 1
            cache_stats = self.cache.stats
            if progress:
                state = progress.update(phase, completed_units=completed_units, cache_hits=cache_stats["hits"],
                                        cache_misses=cache_stats["misses"], replay_count=completed_units)
                print(f"{phase.upper()} {item} | {completed_units}/{unit_total} | elapsed={state['elapsed_seconds']:.1f}s | eta={state['estimated_remaining_seconds']!s}s")
            if partial_report_path:
                partial["progress"] = progress.update(phase, completed_units=completed_units, cache_hits=cache_stats["hits"],
                                                       cache_misses=cache_stats["misses"], replay_count=completed_units) if progress else {}
                atomic_json_write(partial_report_path, partial)
        phase9 = Phase9ValidationOrchestrator(self.settings, baseline_iterations=self.baseline_iterations)
        loading_parameters = {"dataset_identity": dataset_identity}
        if checkpoint_store and checkpoint_store.load("data_loading", loading_parameters) is None:
            checkpoint_store.save("data_loading", loading_parameters, {"symbols": sorted(candles_by_symbol),
                                  "candles": sum(len(values) for values in candles_by_symbol.values())})
        update("data-loading", "1/1")
        started = perf_counter()
        per_symbol = await self._run_symbol_baselines(candles_by_symbol, metadata, checkpoint_store, update, partial)
        timings["baseline_replay_seconds"] = perf_counter() - started
        audits = [audit for result in per_symbol.values() for audit in result["audits"]]
        ordered_times = [candle.open_time for candles in candles_by_symbol.values() for candle in candles]
        windows = rolling_windows(min(ordered_times), max(ordered_times)) if ordered_times else ()
        started = perf_counter()
        walk = await self._walk_forward_checkpointed(candles_by_symbol, windows, checkpoint_store, update, progress)
        timings["walk_forward_seconds"] = perf_counter() - started
        started = perf_counter()
        sensitivity = await self._sensitivity_checkpointed(candles_by_symbol, sensitivity_dimensions, checkpoint_store, update, progress) if sensitivity_dimensions else None
        timings["sensitivity_seconds"] = perf_counter() - started
        complete = bool(windows and sensitivity is not None and not sensitivity.unsupported_parameters and
                        all(result["baseline"] is not None for result in per_symbol.values()) and
                        not (progress and progress.errors))
        started = perf_counter()
        htf = await self._htf_experiment_checkpointed(candles_by_symbol, checkpoint_store, update, progress)
        timings["htf_experiment_seconds"] = perf_counter() - started
        baseline_percentiles = [result["baseline"].percentile for result in per_symbol.values() if result["baseline"]]
        positive_symbols = sum(result["metrics"].expectancy_r > 0 for result in per_symbol.values())
        gate_input = {
            "status": "VALIDATED" if complete else "INCOMPLETE_VALIDATION_ORCHESTRATION",
            "validation_label": validation_label,
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
        monte_parameters = {"iterations": self.monte_carlo_iterations, "seed": self.random_seed}
        monte_carlo = checkpoint_store.load("monte_carlo", monte_parameters) if checkpoint_store else None
        if monte_carlo is None:
            monte_carlo = monte_carlo_ordering(audits, iterations=self.monte_carlo_iterations, random_seed=self.random_seed)
            if checkpoint_store: checkpoint_store.save("monte_carlo", monte_parameters, monte_carlo)
        update("monte-carlo", f"{self.monte_carlo_iterations}/{self.monte_carlo_iterations}")
        timings["monte_carlo_seconds"] = perf_counter() - started
        started = perf_counter()
        leave_one_out = (leave_one_symbol_out(audits, self.settings.historical.symbols)
                         if len(self.settings.historical.symbols) > 1
                         else {"status": "NOT_APPLICABLE_SINGLE_SYMBOL_UNIVERSE", "symbols": list(self.settings.historical.symbols)})
        cost_stress = cost_stress_report(audits, self.settings)
        timings["aggregation_seconds"] = perf_counter() - started
        update("aggregation", "1/1")
        methodology = {**metadata, "analysis_scopes": {
            "strategy_performance": "canonical strategy, exit, and cost audit metrics",
            "sequence_risk_monte_carlo": "trade-order permutations only; not evidence of strategy edge",
            "sensitivity": "owner-supplied observations; no parameter selection",
            "oos_validation": "calendar walk-forward chronological output",
            "lifecycle": "persisted entity-linked events only",
            "cost_stress": "existing CostModel repricing with explicit scenarios",
        }}
        report = {
            "schema_version": "research-report-v1",
            "research_run_id": metadata["research_run_id"],
            "status": "READY_FOR_HUMAN_REVIEW" if complete else "INCOMPLETE_VALIDATION",
            "validation_scope": validation_label or ("OFFICIAL_MULTI_SYMBOL_VALIDATION" if len(candles_by_symbol) > 1 else "SINGLE_SYMBOL_DIAGNOSTIC"),
            "methodology": {**methodology, "dataset_identity": dataset_identity,
                              "checkpoint_mode": checkpoint_mode},
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
                            "cache": self.cache.stats, "candles_processed_input": sum(len(candles) for candles in candles_by_symbol.values()),
                            "phase_elapsed_seconds": timings},
        }
        if progress: progress.update("completed", completed_units=completed_units, cache_hits=self.cache.stats["hits"],
                                     cache_misses=self.cache.stats["misses"], replay_count=report["performance"]["replay_count"]["total"],
                                     status="INCOMPLETE" if progress.errors else "COMPLETED")
        if partial_report_path:
            report["status"] = report["status"]
            atomic_json_write(partial_report_path, report)
        return report

    async def _run_symbol_baselines(self, candles_by_symbol: dict[str, Sequence[Candle]], metadata: dict[str, Any],
                                    checkpoint_store: ResearchCheckpointStore | None, update, partial: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run only independent canonical symbol baselines in OS processes.

        Results are inserted in the input's stable symbol order after completion,
        so process completion order cannot affect audit ordering or any metric.
        """
        ordered_symbols = tuple(candles_by_symbol)
        results: dict[str, Any] = {}
        pending: dict[str, tuple[Sequence[Candle], str]] = {}
        for symbol in ordered_symbols:
            candles = candles_by_symbol[symbol]
            parameters = {"symbol": symbol, "variant": "canonical-baseline"}
            saved = checkpoint_store.load("baseline", parameters) if checkpoint_store else None
            if saved is not None:
                results[symbol] = saved
                if partial is not None: partial["baseline_completed_symbols"] = sorted(results)
                update("baseline", f"{len(results)}/{len(ordered_symbols)}")
                continue
            dates = [candle.open_time for candle in candles]
            key = replay_cache_key(git_commit=metadata["git_commit"], strategy_version=metadata["strategy_version"],
                                   configuration_hash=metadata["configuration_hash"], symbol=symbol,
                                   timeframes=tuple(self.settings.historical.timeframes),
                                   start=min(dates).isoformat() if dates else None, end=max(dates).isoformat() if dates else None,
                                   variant="canonical-baseline")
            if key in self.cache._values:
                self.cache._hits += 1
                results[symbol] = self.cache._values[key]
                if checkpoint_store: checkpoint_store.save("baseline", parameters, results[symbol])
                if partial is not None: partial["baseline_completed_symbols"] = sorted(results)
                update("baseline", f"{len(results)}/{len(ordered_symbols)}")
                continue
            pending[symbol] = (candles, key)
        if pending:
            max_workers = min(self.max_workers or (os.cpu_count() or 1), len(pending))
            loop = asyncio.get_running_loop()
            with self.executor_factory(max_workers=max_workers) as pool:
                futures = {symbol: loop.run_in_executor(pool, _run_symbol_validation_sync, self.settings, candles,
                                                         self.baseline_iterations)
                           for symbol, (candles, _) in pending.items()}
                remaining = dict(futures)
                while remaining:
                    done, _ = await asyncio.wait(tuple(remaining.values()), return_when=asyncio.FIRST_COMPLETED)
                    for future in done:
                        symbol = next(name for name, candidate in remaining.items() if candidate is future)
                        del remaining[symbol]
                        try:
                            result = future.result()
                        except Exception as error:
                            raise RuntimeError(f"baseline validation failed for {symbol}: {error}") from error
                        results[symbol] = result
                        _, key = pending[symbol]
                        self.cache._misses += 1
                        self.cache._values[key] = result
                        if checkpoint_store:
                            checkpoint_store.save("baseline", {"symbol": symbol, "variant": "canonical-baseline"}, result)
                        if partial is not None: partial["baseline_completed_symbols"] = sorted(results)
                        update("baseline", f"{len(results)}/{len(ordered_symbols)}")
        return {symbol: results[symbol] for symbol in ordered_symbols}

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

    async def _walk_forward_checkpointed(self, candles_by_symbol, windows, store, update, progress) -> WalkForwardResult:
        records, oos_audits = [], []
        for window_index, window in enumerate(windows):
            in_count = out_count = 0
            window_oos = []
            for symbol, candles in candles_by_symbol.items():
                parameters = {"window": window_index, "symbol": symbol,
                              "in_start": window.in_sample_start.isoformat(), "out_end": window.out_sample_end.isoformat()}
                result = store.load("walk_forward", parameters) if store else None
                if result is None:
                    try:
                        scoped = [c for c in candles if window.in_sample_start <= c.open_time < window.out_sample_end]
                        result = await build_symbol_validation(self.settings, scoped, baseline_iterations=1, include_baseline=False)
                        if store: store.save("walk_forward", parameters, result)
                    except Exception as exc:
                        if progress: progress.error("walk_forward", parameters, exc)
                        update("walk-forward", f"{window_index + 1}/{len(windows)} FAILED")
                        continue
                for audit in result["audits"]:
                    if window.out_sample_start <= audit.signal_time < window.out_sample_end:
                        window_oos.append(audit); out_count += 1
                    elif window.in_sample_start <= audit.signal_time < window.in_sample_end: in_count += 1
                update("walk-forward", f"{window_index + 1}/{len(windows)} {symbol}")
            oos_audits.extend(window_oos)
            values = [a.net_r for a in window_oos if a.net_r is not None]
            records.append({"in_sample_trades": in_count, "out_sample_trades": out_count, "out_sample_total_r": sum(values, Decimal(0)),
                            "in_sample_start": window.in_sample_start.isoformat(), "in_sample_end": window.in_sample_end.isoformat(),
                            "out_sample_start": window.out_sample_start.isoformat(), "out_sample_end": window.out_sample_end.isoformat()})
        values = [a.net_r for a in oos_audits if a.net_r is not None]
        return WalkForwardResult(tuple(records), len(values), sum(values, Decimal(0)), sum(values, Decimal(0)) / Decimal(len(values)) if values else Decimal(0))

    async def _sensitivity_checkpointed(self, candles_by_symbol, dimensions, store, update, progress) -> SensitivityResult:
        points, unsupported = [], []
        for parameter, values in dimensions.items():
            for value in values:
                parameters = {"parameter": parameter, "value": str(value)}
                point = store.load("sensitivity", parameters) if store else None
                if point is None:
                    try:
                        tuned = _replace_frozen_setting(self.settings, parameter, value)
                        audits = []
                        for candles in candles_by_symbol.values():
                            audits.extend((await build_symbol_validation(tuned, candles, baseline_iterations=1, include_baseline=False))["audits"])
                        point = SensitivityPoint(parameter, Decimal(str(value)), calculate_metrics(audits).expectancy_r)
                        if store: store.save("sensitivity", parameters, point)
                    except ValueError:
                        unsupported.append(parameter); update("sensitivity", f"{parameter} unsupported"); continue
                    except Exception as exc:
                        if progress: progress.error("sensitivity", parameters, exc)
                        update("sensitivity", f"{parameter}={value} FAILED"); continue
                points.append(point); update("sensitivity", f"{parameter}={value}")
        grouped = {}
        for point in points: grouped.setdefault(point.parameter, []).append(point)
        plateau = max((sum(abs(p.expectancy_r - max(x.expectancy_r for x in group)) <= Decimal("0.05") for p in group) for group in grouped.values()), default=0)
        return SensitivityResult(tuple(points), plateau, None, tuple(dict.fromkeys(unsupported)))

    async def _htf_experiment_checkpointed(self, candles_by_symbol, store, update, progress) -> dict[str, Any]:
        variants = {"15M_ONLY": (self.settings.primary_timeframe,), "15M_1H": (self.settings.primary_timeframe, "1h"), "15M_1H_4H": (self.settings.primary_timeframe, "1h", "4h")}
        result = {}
        for name, timeframes in variants.items():
            audits = []
            for symbol, candles in candles_by_symbol.items():
                parameters = {"variant": name, "symbol": symbol, "timeframes": timeframes}
                validation = store.load("htf", parameters) if store else None
                if validation is None:
                    try:
                        validation = await build_symbol_validation(self.settings, [c for c in candles if c.timeframe in timeframes], baseline_iterations=1, include_baseline=False)
                        if store: store.save("htf", parameters, validation)
                    except Exception as exc:
                        if progress: progress.error("htf", parameters, exc)
                        update("htf", f"{name} {symbol} FAILED"); continue
                audits.extend(validation["audits"]); update("htf", f"{name} {symbol}")
            result[name] = {**_metrics_summary(audits), "timeframes": list(timeframes), "canonical_cost_exit_engine": True}
        return result


def _metrics_summary(audits):
    metrics = calculate_metrics(audits)
    return {"trade_count": metrics.trade_count, "win_rate": metrics.win_rate,
            "expectancy_r": metrics.expectancy_r, "average_r": metrics.expectancy_r,
            "profit_factor": metrics.profit_factor, "max_drawdown_r": metrics.max_drawdown_r,
            "total_r": metrics.total_r}


def _dataset_identity(candles_by_symbol: dict[str, Sequence[Candle]]) -> str:
    """A compact cache identity for exact loaded series, not merely date bounds."""
    series = []
    for symbol, candles in sorted(candles_by_symbol.items()):
        for candle in sorted(candles, key=lambda item: (item.timeframe, item.open_time)):
            series.append((symbol, candle.timeframe, candle.open_time.isoformat(), candle.close_time.isoformat(),
                           str(candle.open), str(candle.high), str(candle.low), str(candle.close), str(candle.volume), candle.is_closed))
    return hashlib.sha256(json.dumps(series, separators=(",", ":")).encode("utf-8")).hexdigest()


def write_research_outputs(report: dict[str, Any], *, json_path: str | Path, csv_path: str | Path | None = None) -> None:
    """Persist a versioned JSON report and a concise top-level CSV summary."""
    destination = Path(json_path)
    atomic_json_write(destination, report)
    if csv_path is not None:
        output = Path(csv_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=("scope", "trade_count", "expectancy_r", "total_r", "max_drawdown_r", "profit_factor"))
            writer.writeheader()
            source = report.get("leave_one_symbol_out", report.get("entry_mode_comparison", {}))
            for scope, values in source.items():
                if isinstance(values, dict):
                    metrics = values.get("leave_one_symbol_out", {}).get("combined", values)
                    writer.writerow({"scope": scope, **{name: metrics.get(name) for name in writer.fieldnames[1:]}})


if __name__ == "__main__":
    from app.backtest.phase9_cli import main
    raise SystemExit(main())
