"""Run a sequential diagnostic replay: ``python -m app.backtest``."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone, timedelta
import json

from app.backtest.report import HistoricalPerformanceReport
from app.backtest_runner import HistoricalBacktestRunner
from app.config.settings import load_settings, normalize_symbol
from app.storage.database import Database
from app.storage.repositories import BacktestRepository, CandleRepository


async def run(args) -> int:
    settings = load_settings(args.config)
    symbol = normalize_symbol(args.symbol)
    timeframe = args.timeframe.lower()
    database = Database(settings.database_path); database.open()
    candle_repository = CandleRepository(database)
    candles = candle_repository.load_range(symbol, timeframe, datetime(1970, 1, 1, tzinfo=timezone.utc), datetime.now(timezone.utc) + timedelta(minutes=1))
    if not candles:
        print(f"No stored candles for {symbol} {timeframe}")
        database.close(); return 2
    repository = BacktestRepository(database)
    run = await HistoricalBacktestRunner(settings, repository).run(candles)
    report = HistoricalPerformanceReport(repository).run(run.run_id)
    print(json.dumps(report, default=str, indent=2))
    database.close(); return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Sequential historical CSD replay")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--timeframe", default="15m")
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
