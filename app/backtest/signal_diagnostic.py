"""Small, read-only signal diagnostic over the canonical frozen V1 replay seam."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Sequence

from app.backtest.data_integrity import check_integrity
from app.backtest.metrics import calculate_metrics
from app.backtest.phase9 import CanonicalTradeSimulator, collect_strategy_plans
from app.backtest.research_checkpoints import jsonable
from app.config.settings import Settings
from app.events.models import Candle
from app.strategy.scoring import frozen_v1_score_semantics


async def seven_day_signal_report(settings: Settings, candles: Sequence[Candle], *, start: datetime, end: datetime) -> dict[str, Any]:
    """Replay supplied warmup+test candles, reporting plans created in [start,end)."""
    closed = tuple(c for c in candles if c.is_closed)
    _, plans = await collect_strategy_plans(settings, closed)
    test_plans = tuple(plan for plan in plans if start <= plan.signal_candle.open_time < end)
    simulator = CanonicalTradeSimulator(settings, closed)
    audits = [audit for index, plan in enumerate(test_plans)
              if (audit := simulator.simulate(plan, closed, f"eth-7day-{index}")) is not None]
    audit_by_time = {audit.signal_time: audit for audit in audits}
    rows = [_signal_row(plan, audit_by_time.get(plan.signal_candle.close_time)) for plan in test_plans]
    metrics = calculate_metrics(audits)
    data = {}
    for timeframe in settings.timeframes:
        scoped = [c for c in closed if c.timeframe == timeframe and start <= c.open_time < end]
        integrity = check_integrity("ETHUSDT", timeframe, scoped)
        data[timeframe] = {"candle_count": len(scoped), "first": scoped[0].open_time if scoped else None,
                           "last": scoped[-1].close_time if scoped else None, "gaps": len(integrity.gaps),
                           "duplicates": integrity.duplicate_open_times, "malformed": integrity.ohlc_violations,
                           "closed_candles_only": all(c.is_closed for c in scoped),
                           "status": "OK" if integrity.is_clean else "INCOMPLETE_DATA"}
    scores = Counter(str(row["score"]) for row in rows)
    regimes = Counter(str(row["regime"]) for row in rows)
    directions = Counter(str(row["direction"]) for row in rows)
    return {
        "schema_version": "eth-7day-signal-test-v1", "validation_scope": "ETHUSDT_7DAY_SIGNAL_TEST",
        "disclaimer": "This is a diagnostic signal test, NOT statistical proof of strategy edge and NOT a go-live validation.",
        "data": {"symbol": "ETHUSDT", "start": start, "end": end, "timeframes": data,
                 "warmup_candles_excluded_from_test_window": len(closed) - sum(item["candle_count"] for item in data.values())},
        "signal_summary": {"total_signals": len(rows), "long_count": directions.get("BULLISH", 0),
                           "short_count": directions.get("BEARISH", 0),
                           "average_score": sum((row["score"] for row in rows), Decimal(0)) / Decimal(len(rows)) if rows else None,
                           "score_distribution": dict(scores), "regime_distribution": dict(regimes)},
        "signals": rows, "timeline": [{key: row[key] for key in ("timestamp", "classification", "direction", "score", "entry_range", "stop", "tp1", "tp2", "tp3", "outcome")} for row in rows],
        "performance": {**asdict(metrics), "statistical_status": "INSUFFICIENT_SAMPLE_FOR_STATISTICAL_CONCLUSION" if metrics.trade_count < 30 else "DIAGNOSTIC_ONLY_NOT_STATISTICAL_PROOF"},
        "methodology": {"canonical_strategy_engine": True, "canonical_cost_model": True, "canonical_exit_engine": True,
                        "forming_candles_excluded": True, "test_window_days": 7,
                        "frozen_v1_score_semantics": frozen_v1_score_semantics()},
    }


def _signal_row(plan, audit) -> dict[str, Any]:
    assessment, analysis, confirmation = plan.assessment, plan.analysis, plan.assessment.confirmation
    setup = assessment.retest.setup
    return {"timestamp": plan.signal_candle.close_time, "direction": str(analysis.direction), "score": assessment.score.total,
            "classification": str(assessment.score.classification), "regime": analysis.regime,
            "entry_range": {"low": analysis.entry_low, "high": analysis.entry_high}, "reference_entry": analysis.reference_entry,
            "stop": analysis.stop_loss, "tp1": analysis.take_profits[0], "tp2": analysis.take_profits[1], "tp3": analysis.take_profits[2],
            "csd": {"timestamp": setup.source_csd.candle.close_time, "close_distance_percent": setup.source_csd.close_distance_percent},
            "breakout": {"level": setup.breakout_level, "quality": setup.quality},
            "retest": {"timestamp": assessment.retest.candle.close_time, "quality": assessment.retest.quality},
            "ema": confirmation.ema, "rsi": confirmation.rsi, "macd": confirmation.macd, "volume": confirmation.volume,
            "one_hour_context": confirmation.one_hour, "four_hour_context": confirmation.four_hour,
            "outcome": audit.exit_reason if audit else "UNRESOLVED_OR_UNFILLED", "exit_reason": audit.exit_reason if audit else None,
            "net_r": audit.net_r if audit else None, "gross_r": audit.gross_r if audit else None,
            "mfe_r": audit.mfe_r if audit else None, "mae_r": audit.mae_r if audit else None,
            "holding_bars": audit.bars_in_trade if audit else None, "costs_r": audit.costs_r if audit else None,
            "exit_timestamp": audit.exit_time if audit else None}


def markdown_report(report: dict[str, Any]) -> str:
    lines = ["# ETHUSDT Seven-Day Signal Test", "", f"**Scope:** `{report['validation_scope']}`", "", report["disclaimer"], "",
             "## Signal timeline", "", "| Time | Signal | Direction | Score | Entry | SL | TP1 | TP2 | TP3 | Outcome |", "|---|---|---|---:|---|---|---|---|---|---|"]
    for row in report["timeline"]:
        entry = row["entry_range"]
        lines.append(f"| {row['timestamp']} | {row['classification']} | {row['direction']} | {row['score']} | {entry['low']}–{entry['high']} | {row['stop']} | {row['tp1']} | {row['tp2']} | {row['tp3']} | {row['outcome']} |")
    lines.extend(["", "## Performance", "", f"Completed trades: {report['performance']['trade_count']}", f"Status: `{report['performance']['statistical_status']}`"])
    return "\n".join(lines) + "\n"
