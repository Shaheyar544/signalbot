"""Cost-aware, deterministic performance statistics for trade audits."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from math import sqrt
from typing import Sequence

from app.backtests import TradeAudit


@dataclass(frozen=True)
class PerformanceMetrics:
    trade_count: int
    wins: int
    losses: int
    win_rate: Decimal
    win_rate_ci_low: Decimal
    win_rate_ci_high: Decimal
    expectancy_r: Decimal
    total_r: Decimal
    gross_r: Decimal
    total_cost_r: Decimal
    profit_factor: Decimal | None
    profit_factor_status: str
    max_drawdown_r: Decimal
    longest_losing_streak: int
    ambiguous_intrabar_count: int
    average_bars_in_trade: Decimal | None
    by_confidence: dict[str, dict[str, Decimal | int]]
    by_direction: dict[str, dict[str, Decimal | int]]
    by_month: dict[str, dict[str, Decimal | int]]
    mfe_distribution: tuple[Decimal, ...] = ()
    mae_distribution: tuple[Decimal, ...] = ()
    by_symbol: dict[str, dict[str, Decimal | int]] = field(default_factory=dict)
    by_regime: dict[str, dict[str, Decimal | int]] = field(default_factory=dict)
    by_session: dict[str, dict[str, Decimal | int]] = field(default_factory=dict)


def _wilson(wins: int, total: int) -> tuple[Decimal, Decimal]:
    if not total:
        return Decimal(0), Decimal(0)
    z = 1.959963984540054
    p = wins / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    spread = z * sqrt((p * (1 - p) / total) + z * z / (4 * total * total)) / denominator
    return Decimal(str(max(0.0, centre - spread))), Decimal(str(min(1.0, centre + spread)))


def _bucket_by(trades: Sequence[TradeAudit], key):
    groups: dict[str, list[TradeAudit]] = {}
    for trade in trades:
        groups.setdefault(str(key(trade)), []).append(trade)
    result = {}
    for name, items in groups.items():
        values = [item.net_r for item in items if item.net_r is not None]
        wins = sum(value > 0 for value in values)
        positive = sum((value for value in values if value > 0), Decimal(0))
        negative = abs(sum((value for value in values if value < 0), Decimal(0)))
        result[name] = {"trades": len(items), "wins": wins, "losses": len(values) - wins,
                        "win_rate": Decimal(wins) / len(values) if values else Decimal(0),
                        "total_r": sum(values, Decimal(0)),
                        "expectancy_r": sum(values, Decimal(0)) / len(values) if values else Decimal(0),
                        "profit_factor": positive / negative if negative else None}
    return result


def calculate_metrics(trades: Sequence[TradeAudit]) -> PerformanceMetrics:
    net = [trade.net_r for trade in trades if trade.net_r is not None]
    gross = [trade.gross_r for trade in trades if trade.gross_r is not None]
    costs = [trade.costs_r for trade in trades if trade.costs_r is not None]
    wins = sum(value > 0 for value in net)
    losses = sum(value <= 0 for value in net)
    low, high = _wilson(wins, len(net))
    equity = Decimal(0); peak = Decimal(0); drawdown = Decimal(0); streak = longest = 0
    for value in net:
        equity += value
        peak = max(peak, equity)
        drawdown = min(drawdown, equity - peak)
        if value <= 0:
            streak += 1; longest = max(longest, streak)
        else:
            streak = 0
    positive = sum((value for value in net if value > 0), Decimal(0))
    negative = abs(sum((value for value in net if value < 0), Decimal(0)))
    average_bars = [trade.bars_in_trade for trade in trades if trade.bars_in_trade is not None]
    mfe = tuple(trade.mfe_r for trade in trades if trade.mfe_r is not None)
    mae = tuple(trade.mae_r for trade in trades if trade.mae_r is not None)
    by_confidence = _bucket_by(trades, lambda item: item.score_classification)
    by_direction = _bucket_by(trades, lambda item: item.direction)
    by_month = _bucket_by(trades, lambda item: item.signal_time.strftime("%Y-%m"))
    by_symbol = _bucket_by(trades, lambda item: item.symbol or "UNKNOWN")
    by_regime = _bucket_by(trades, lambda item: item.regime or "UNKNOWN")
    by_session = _bucket_by(trades, lambda item: item.session or "UNKNOWN")
    return PerformanceMetrics(
        len(net), wins, losses, Decimal(wins) / len(net) if net else Decimal(0), low, high,
        sum(net, Decimal(0)) / len(net) if net else Decimal(0), sum(net, Decimal(0)),
        sum(gross, Decimal(0)), sum(costs, Decimal(0)), positive / negative if negative else None,
        "INSUFFICIENT_SAMPLE" if not net else ("DEFINED" if negative else "UNDEFINED_NO_LOSSES"),
        abs(drawdown), longest, sum(trade.ambiguous_intrabar for trade in trades),
        sum(average_bars, 0) / Decimal(len(average_bars)) if average_bars else None,
        by_confidence, by_direction, by_month, mfe, mae, by_symbol, by_regime, by_session,
    )
