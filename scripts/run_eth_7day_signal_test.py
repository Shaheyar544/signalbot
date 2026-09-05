"""Run a fast, read-only seven-day ETHUSDT frozen-strategy signal diagnostic."""
from __future__ import annotations

import argparse
import asyncio
import csv
from datetime import timedelta
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backtest.research_checkpoints import atomic_json_write, jsonable
from app.backtest.signal_diagnostic import markdown_report, seven_day_signal_report
from app.config.settings import load_settings
from app.storage.database import Database
from app.storage.repositories import CandleRepository


async def run(args) -> int:
    settings = load_settings(args.config)
    database = Database(settings.database_path); database.open()
    try:
        connection = database.connection
        assert connection is not None
        row = connection.execute("SELECT MAX(close_time) FROM candles WHERE symbol='ETHUSDT' AND timeframe=? AND is_closed=1", (settings.primary_timeframe,)).fetchone()
        if not row or not row[0]:
            raise RuntimeError("No closed ETHUSDT 15m candles are available")
        end = __import__("datetime").datetime.fromisoformat(row[0])
        start = end - timedelta(days=7)
        warmup_start = start - timedelta(days=90)
        repository = CandleRepository(database)
        candles = [candle for timeframe in settings.timeframes for candle in repository.load_range("ETHUSDT", timeframe, warmup_start, end)]
        report = await seven_day_signal_report(settings, candles, start=start, end=end)
        atomic_json_write(args.report, report)
        with Path(args.csv).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=("timestamp", "classification", "direction", "score", "entry_low", "entry_high", "stop", "tp1", "tp2", "tp3", "outcome", "net_r"))
            writer.writeheader()
            for signal in report["signals"]:
                writer.writerow({"timestamp": signal["timestamp"], "classification": signal["classification"], "direction": signal["direction"], "score": signal["score"],
                                 "entry_low": signal["entry_range"]["low"], "entry_high": signal["entry_range"]["high"], "stop": signal["stop"], "tp1": signal["tp1"], "tp2": signal["tp2"], "tp3": signal["tp3"], "outcome": signal["outcome"], "net_r": signal["net_r"]})
        Path(args.markdown).write_text(markdown_report(report), encoding="utf-8")
        print(f"scope={report['validation_scope']} start={start.isoformat()} end={end.isoformat()} signals={report['signal_summary']['total_signals']} completed={report['performance']['trade_count']} report={args.report}")
        return 0
    finally:
        database.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast frozen-V1 ETHUSDT seven-day signal diagnostic")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--report", default="data/eth_7day_signal_test.json")
    parser.add_argument("--csv", default="data/eth_7day_signal_test.csv")
    parser.add_argument("--markdown", default="data/eth_7day_signal_test.md")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
