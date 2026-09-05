"""Structured diagnostic and validation reports for historical runs."""
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import random
from typing import Sequence

from app.backtests import BacktestRun, TradeAudit
from app.backtest.metrics import PerformanceMetrics, calculate_metrics
from app.storage.repositories import BacktestRepository


def _metric_dict(metrics: PerformanceMetrics) -> dict:
    return {key: value for key, value in asdict(metrics).items()}


def random_baseline(trades: Sequence[TradeAudit], *, iterations: int = 1000, seed: int = 7) -> dict:
    """Permutation baseline, preserving trade count and observed return distribution."""
    values = [trade.net_r for trade in trades if trade.net_r is not None]
    if not values:
        return {"iterations": iterations, "percentile": Decimal(0), "p_value": Decimal(1), "strategy_expectancy_r": Decimal(0)}
    rng = random.Random(seed)
    target = sum(values, Decimal(0)) / len(values)
    samples = []
    for _ in range(iterations):
        shuffled = list(values); rng.shuffle(shuffled)
        samples.append(sum(shuffled, Decimal(0)) / len(shuffled))
    at_or_better = sum(sample >= target for sample in samples)
    percentile = Decimal(sum(sample <= target for sample in samples) * 100) / iterations
    return {"iterations": iterations, "percentile": percentile,
            "p_value": Decimal(at_or_better) / iterations,
            "strategy_expectancy_r": target}


class HistoricalPerformanceReport:
    def __init__(self, repository: BacktestRepository) -> None:
        self.repository = repository

    def run(self, run_id: str, *, baseline_iterations: int = 1000) -> dict:
        run = self.repository.get_run(run_id)
        if run is None:
            raise KeyError(f"Unknown backtest run: {run_id}")
        trades = self.repository.list_trades(run_id)
        metrics = calculate_metrics(trades)
        baseline = random_baseline(trades, iterations=baseline_iterations)
        status = "INCOMPLETE_EXIT_MODEL" if run.status.value.startswith("INCOMPLETE_EXIT") else (
            "INCOMPLETE_COST_MODEL" if run.status.value.startswith("INCOMPLETE_COST") else run.status.value)
        result = {
            "run_id": run.run_id, "symbol": run.symbol, "timeframe": run.timeframe,
            "status": status, "warnings": list(run.warnings), "created_at": run.created_at.isoformat(),
            "metrics": _metric_dict(metrics), "baseline": baseline,
            "ambiguous_intrabar_count": metrics.ambiguous_intrabar_count,
            "backtest_policy": "SAME_CANDLE: SL-first; ambiguous trades included",
            "cost_model": "Configured CostModel; gross is diagnostic and net is reported",
        }
        result.update({"trade_count": metrics.trade_count, "wins": metrics.wins, "losses": metrics.losses,
                       "win_rate": metrics.win_rate, "expectancy_r": metrics.expectancy_r,
                       "total_r": metrics.total_r, "gross_r": metrics.gross_r,
                       "total_cost_r": metrics.total_cost_r, "profit_factor": metrics.profit_factor,
                       "max_drawdown_r": metrics.max_drawdown_r})
        return result

    @staticmethod
    def from_trades(run: BacktestRun, trades: Sequence[TradeAudit], *, baseline_iterations: int = 1000) -> dict:
        metrics = calculate_metrics(trades)
        return {"run_id": run.run_id, "status": run.status.value, "warnings": list(run.warnings),
                "metrics": _metric_dict(metrics), "baseline": random_baseline(trades, iterations=baseline_iterations),
                "ambiguous_intrabar_count": metrics.ambiguous_intrabar_count}
