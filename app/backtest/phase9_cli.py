"""Command-line execution for the frozen, read-only Phase 9 validation pipeline."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Sequence

from app.backtest.phase9_config import load_sensitivity_config
from app.backtest.research_orchestrator import UnifiedResearchOrchestrator, write_research_outputs
from app.backtest.research_scope import scoped_research_settings, validation_scope
from app.config.settings import Settings, load_settings, normalize_symbol
from app.storage.database import Database
from app.storage.repositories import CandleRepository


def parse_entry_modes(value: str) -> tuple[str, ...]:
    modes = tuple(dict.fromkeys(part.strip().lower() for part in value.split(",") if part.strip()))
    if not modes or any(mode not in {"retest", "immediate"} for mode in modes):
        raise ValueError("entry modes must be a non-empty comma-separated subset of retest, immediate")
    return modes


def entry_mode_settings(settings: Settings, entry_mode: str) -> Settings:
    """Return an isolated research variant; never mutates production configuration."""
    if entry_mode not in {"retest", "immediate"}:
        raise ValueError("entry mode must be retest or immediate")
    return replace(settings, variants=replace(settings.variants, entry_mode=entry_mode))


def _default_paths() -> tuple[str, str]:
    date_label = datetime.now(timezone.utc).date().isoformat()
    return (f"data/validation_report_{date_label}.json", f"data/validation_summary_{date_label}.csv")


async def run(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    symbols = tuple(normalize_symbol(value) for value in args.symbols.split(",")) if args.symbols else settings.historical.symbols
    modes = parse_entry_modes(args.entry_modes)
    base_settings = scoped_research_settings(settings, symbols)
    base_label = validation_scope(symbols, args.validation_label)
    start = datetime.fromisoformat(args.start).astimezone(timezone.utc) if args.start else datetime(1970, 1, 1, tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).astimezone(timezone.utc) if args.end else datetime.now(timezone.utc)
    report_path, csv_path = _default_paths()
    report_path, csv_path = args.report or report_path, args.csv or csv_path
    sensitivity = load_sensitivity_config(args.sensitivity)
    database = Database(settings.database_path); database.open()
    try:
        repository = CandleRepository(database)
        loading_started = perf_counter()
        candles = {symbol: [candle for timeframe in settings.historical.timeframes
                            for candle in repository.load_range(symbol, timeframe, start, end)] for symbol in symbols}
        loading_seconds = perf_counter() - loading_started
        reports: dict[str, dict[str, Any]] = {}
        for entry_mode in modes:
            variant = entry_mode_settings(base_settings, entry_mode)
            reports[entry_mode] = await UnifiedResearchOrchestrator(
                variant, baseline_iterations=args.iterations, monte_carlo_iterations=args.monte_carlo_iterations,
                random_seed=args.random_seed,
            ).run(
                candles, sensitivity_dimensions=sensitivity,
                checkpoint_root=Path(args.checkpoint_dir) / entry_mode,
                progress_path=Path(args.progress_dir) / f"{entry_mode}.json",
                partial_report_path=Path(args.partial_dir) / f"{entry_mode}.json",
                checkpoint_mode="resume" if args.resume else "restart" if args.restart else "fresh",
                validation_label=f"{base_label}:{entry_mode}",
            )
            reports[entry_mode]["performance"]["timings_seconds"]["data_loading_seconds"] = loading_seconds
        report = {
            "schema_version": "phase9-entry-mode-comparison-v1",
            "validation_scope": base_label,
            "entry_modes": list(modes),
            "entry_mode_comparison": reports,
            "status": "READY_FOR_HUMAN_REVIEW" if all(item["status"] == "READY_FOR_HUMAN_REVIEW" for item in reports.values()) else "INCOMPLETE_VALIDATION",
        }
        write_research_outputs(report, json_path=report_path, csv_path=csv_path)
        for mode, item in reports.items():
            gate = item["go_live_gate"]
            trades = item["leave_one_symbol_out"].get("combined", {}).get("trade_count", "N/A")
            print(f"entry_mode={mode} report={report_path} status={item['status']} gate={gate['result']} trades={trades}")
        return 0 if report["status"] == "READY_FOR_HUMAN_REVIEW" else 2
    finally:
        database.close()


def build_parser(*, default_entry_modes: str = "retest,immediate") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the complete frozen-strategy Phase 9 validation pipeline")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--symbols", help="comma-separated symbols; defaults to historical configuration")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--monte-carlo-iterations", type=int, default=1000)
    parser.add_argument("--random-seed", type=int, default=7)
    parser.add_argument("--sensitivity", default="phase9_sensitivity.json")
    parser.add_argument("--entry-modes", default=default_entry_modes, help="retest, immediate, or both comma-separated")
    parser.add_argument("--report", help="final JSON destination; default is data/validation_report_<UTC-date>.json")
    parser.add_argument("--csv", help="final CSV destination; default is data/validation_summary_<UTC-date>.csv")
    parser.add_argument("--checkpoint-dir", default="data/research_checkpoints")
    parser.add_argument("--progress-dir", default="data/research_progress")
    parser.add_argument("--partial-dir", default="data/research_partial")
    parser.add_argument("--validation-label", help="immutable execution label; does not modify config")
    resume_group = parser.add_mutually_exclusive_group()
    resume_group.add_argument("--resume", action="store_true")
    resume_group.add_argument("--restart", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None, *, default_entry_modes: str = "retest,immediate") -> int:
    return asyncio.run(run(build_parser(default_entry_modes=default_entry_modes).parse_args(argv)))

