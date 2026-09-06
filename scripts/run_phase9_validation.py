"""Execute Phase 9A validation over cached historical candles.

This command never selects a parameter. It only records frozen-strategy,
random-entry, walk-forward, and supplied sensitivity observations.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backtest.phase9_cli import main as phase9_main


async def run(args) -> int:
    settings = load_settings(args.config)
    symbols = tuple(normalize_symbol(value) for value in args.symbols.split(",")) if args.symbols else settings.historical.symbols
    run_settings = scoped_research_settings(settings, symbols)
    label = validation_scope(symbols, args.validation_label)
    report_path = args.report or ("data/eth_diagnostic_report.json" if label == "ETHUSDT_DIAGNOSTIC" else "data/phase9_report.json")
    csv_path = args.csv or ("data/eth_diagnostic_summary.csv" if label == "ETHUSDT_DIAGNOSTIC" else "data/phase9_summary.csv")
    progress_path = args.progress or ("data/eth_diagnostic_progress.json" if label == "ETHUSDT_DIAGNOSTIC" else "data/research_progress.json")
    start = datetime.fromisoformat(args.start).astimezone(timezone.utc) if args.start else datetime(1970, 1, 1, tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).astimezone(timezone.utc) if args.end else datetime.now(timezone.utc)
    database = Database(settings.database_path); database.open()
    repository = CandleRepository(database)
    try:
        loading_started = perf_counter()
        candles = {symbol: [candle for timeframe in settings.historical.timeframes
                            for candle in repository.load_range(symbol, timeframe, start, end)] for symbol in symbols}
        loading_seconds = perf_counter() - loading_started
        sensitivity = load_sensitivity_config(args.sensitivity) if args.sensitivity else None
        result = await UnifiedResearchOrchestrator(
            run_settings, baseline_iterations=args.iterations, monte_carlo_iterations=args.monte_carlo_iterations,
            random_seed=args.random_seed,
        ).run(candles, sensitivity_dimensions=sensitivity,
              checkpoint_root=args.checkpoint_dir,
              progress_path=progress_path,
              partial_report_path=report_path,
              checkpoint_mode="resume" if args.resume else "restart" if args.restart else "fresh",
              validation_label=label)
        result["performance"]["timings_seconds"]["data_loading_seconds"] = loading_seconds
        write_research_outputs(result, json_path=report_path, csv_path=csv_path)
        gate = result["go_live_gate"]
        robustness = result["leave_one_symbol_out"]
        trades = robustness.get("combined", {}).get("trade_count", "N/A")
        summary = f"report={report_path} scope={result['validation_scope']} status={result['status']} gate={gate['result']} trades={trades}"
        if args.profile:
            summary += f" timings={result['performance']['timings_seconds']} replays={result['performance']['replay_count']}"
        print(summary)
        return 0 if result["status"] == "READY_FOR_HUMAN_REVIEW" else 2
    finally:
        database.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run frozen-strategy Phase 9A validation")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--symbols", help="comma-separated symbols; defaults to historical configuration")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--monte-carlo-iterations", type=int, default=1000)
    parser.add_argument("--random-seed", type=int, default=7)
    parser.add_argument("--report", help="report path; ETH diagnostic defaults to data/eth_diagnostic_report.json")
    parser.add_argument("--csv", help="CSV path; ETH diagnostic defaults to data/eth_diagnostic_summary.csv")
    parser.add_argument("--profile", action="store_true", help="print per-phase timing and replay-count instrumentation")
    parser.add_argument("--sensitivity", help="JSON mapping of frozen sensitivity dimensions to values")
    resume_group = parser.add_mutually_exclusive_group()
    resume_group.add_argument("--resume", action="store_true", help="reuse only compatible completed checkpoints")
    resume_group.add_argument("--restart", action="store_true", help="discard checkpoints for this exact research identity")
    parser.add_argument("--checkpoint-dir", default="data/research_checkpoints",
                        help="local durable checkpoint root (default: data/research_checkpoints)")
    parser.add_argument("--progress", help="atomic progress path; ETH diagnostic defaults to data/eth_diagnostic_progress.json")
    parser.add_argument("--validation-label", help="immutable execution label recorded in metadata; does not modify config")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(phase9_main(default_entry_modes="retest"))
