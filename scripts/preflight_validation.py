"""Read-only data pre-flight for a full historical research validation."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backtest.data_integrity import check_integrity
from app.backtest.phase9_config import load_sensitivity_config
from app.config.settings import load_settings
from app.storage.database import Database
from app.storage.repositories import CandleRepository

_DELTA = {"15m": timedelta(minutes=15), "1h": timedelta(hours=1), "4h": timedelta(hours=4)}


def run(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    sensitivity = load_sensitivity_config(args.sensitivity)
    database = Database(settings.database_path)
    database.open()
    repository = CandleRepository(database)
    series = []
    failures = []
    try:
        for symbol in settings.historical.symbols:
            for timeframe in settings.historical.timeframes:
                candles = repository.load_range(symbol, timeframe, datetime(1970, 1, 1, tzinfo=timezone.utc), datetime(2100, 1, 1, tzinfo=timezone.utc))
                closed = [candle for candle in candles if candle.is_closed]
                integrity = check_integrity(symbol, timeframe, closed)
                expected = int((integrity.range_end - integrity.range_start) / _DELTA[timeframe]) + 1 if integrity.range_start and integrity.range_end else 0
                coverage_days = (integrity.range_end - integrity.range_start).days if integrity.range_start and integrity.range_end else 0
                status = "OK" if integrity.is_clean and coverage_days >= settings.historical.years * 365 - 7 else "INCOMPLETE_DATA"
                item = {"symbol": symbol, "timeframe": timeframe, "first_candle": integrity.range_start.isoformat() if integrity.range_start else None,
                        "last_candle": integrity.range_end.isoformat() if integrity.range_end else None, "candle_count": len(closed),
                        "expected_candle_count": expected, "gap_count": len(integrity.gaps),
                        "missing_candles": sum(gap.missing_candles for gap in integrity.gaps),
                        "duplicate_count": integrity.duplicate_open_times, "malformed_count": integrity.ohlc_violations,
                        "unclosed_candles_excluded": len(candles) - len(closed), "coverage_days": coverage_days,
                        "chronological": all(left.open_time < right.open_time for left, right in zip(closed, closed[1:])), "status": status}
                series.append(item)
                if status != "OK": failures.append(f"{symbol}:{timeframe}")
    finally:
        database.close()
    payload = {"status": "PASS" if not failures else "PRE_FLIGHT_FAILURE", "generated_at": datetime.now(timezone.utc).isoformat(),
               "symbols": list(settings.historical.symbols), "timeframes": list(settings.historical.timeframes),
               "sensitivity_dimensions": sensitivity, "series": series, "failures": failures,
               "causal_replay": "closed candles sorted chronologically; strategy uses as-of swing gating"}
    Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = ["# Historical Validation Pre-flight", "", f"Status: **{payload['status']}**", "", "| Symbol | TF | Closed | Expected | Gaps | Duplicates | Malformed | Unclosed excluded | Status |", "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    lines += [f"| {item['symbol']} | {item['timeframe']} | {item['candle_count']} | {item['expected_candle_count']} | {item['missing_candles']} | {item['duplicate_count']} | {item['malformed_count']} | {item['unclosed_candles_excluded']} | {item['status']} |" for item in series]
    Path(args.markdown).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"preflight={payload['status']} json={args.json} markdown={args.markdown}")
    return 0 if not failures else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--sensitivity", default="phase9_sensitivity.json")
    parser.add_argument("--json", default="data/preflight_report.json")
    parser.add_argument("--markdown", default="data/preflight_report.md")
    raise SystemExit(run(parser.parse_args()))
