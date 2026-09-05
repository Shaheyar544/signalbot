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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backtest.phase9 import Phase9ValidationOrchestrator
from app.config.settings import load_settings, normalize_symbol
from app.storage.database import Database
from app.storage.repositories import CandleRepository


async def run(args) -> int:
    settings = load_settings(args.config)
    symbols = tuple(normalize_symbol(value) for value in args.symbols.split(",")) if args.symbols else settings.historical.symbols
    start = datetime.fromisoformat(args.start).astimezone(timezone.utc) if args.start else datetime(1970, 1, 1, tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).astimezone(timezone.utc) if args.end else datetime.now(timezone.utc)
    database = Database(settings.database_path); database.open()
    repository = CandleRepository(database)
    try:
        candles = {symbol: [candle for timeframe in settings.historical.timeframes
                            for candle in repository.load_range(symbol, timeframe, start, end)] for symbol in symbols}
        sensitivity = json.loads(Path(args.sensitivity).read_text(encoding="utf-8")) if args.sensitivity else None
        result = await Phase9ValidationOrchestrator(settings, baseline_iterations=args.iterations).run(
            candles, sensitivity_dimensions=sensitivity)
        Path(args.report).write_text(json.dumps(result, default=str, indent=2), encoding="utf-8")
        print(f"report={args.report} status={result['status']}")
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
    parser.add_argument("--report", default="data/phase9_report.json")
    parser.add_argument("--sensitivity", help="JSON mapping of frozen sensitivity dimensions to values")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
