"""Fetch and persist closed Binance USD-M Futures candles in bounded batches."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backtest.data_integrity import check_integrity
from app.config.settings import load_settings, normalize_symbol
from app.data.binance_rest import BinanceRestClient
from app.storage.database import Database
from app.storage.repositories import CandleRepository


async def run(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    symbols = (normalize_symbol(args.symbol),) if args.symbol else settings.historical.symbols
    timeframes = (args.timeframe.lower(),) if args.timeframe else settings.historical.timeframes
    if any(item not in settings.historical.timeframes for item in timeframes):
        raise ValueError("requested timeframe is not enabled in historical.timeframes")
    database = Database(settings.database_path)
    database.open()
    repository = CandleRepository(database)
    client = BinanceRestClient()
    failures = 0
    try:
        for symbol in symbols:
            for timeframe in timeframes:
                end = datetime.now(timezone.utc)
                start = end - timedelta(days=365 * settings.historical.years)
                print(f"fetching {symbol} {timeframe} from {start.isoformat()} to {end.isoformat()}", flush=True)
                try:
                    fetched = await client.fetch_candles_range(symbol, timeframe, start, end)
                    closed = [candle for candle in fetched if candle.is_closed]
                    for offset in range(0, len(closed), 5000):
                        repository.upsert_many(closed[offset:offset + 5000])
                    report = check_integrity(symbol, timeframe, closed)
                    first = closed[0].open_time.isoformat() if closed else "n/a"
                    last = closed[-1].open_time.isoformat() if closed else "n/a"
                    severe_gaps = sum(g.missing_candles for g in report.gaps if g.missing_candles > args.max_missing_gap)
                    status = "CLEAN" if (not report.empty and not report.duplicate_open_times and
                                         not report.ohlc_violations and severe_gaps == 0) else "ISSUES"
                    print(f"{symbol} {timeframe}: candles={len(closed)} range={first}..{last} "
                          f"gaps={sum(g.missing_candles for g in report.gaps)} "
                          f"duplicates={report.duplicate_open_times} invalid_ohlc={report.invalid_ohlc} status={status}", flush=True)
                    if status != "CLEAN":
                        failures += 1
                except Exception as error:  # keep other configured pairs processing
                    failures += 1
                    print(f"{symbol} {timeframe}: FAILED: {error}", file=sys.stderr, flush=True)
    finally:
        await client.close()
        database.close()
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch historical Binance futures candles")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--symbol")
    parser.add_argument("--timeframe")
    parser.add_argument("--max-missing-gap", type=int, default=3,
                        help="fail integrity only when a gap exceeds this many candles")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
