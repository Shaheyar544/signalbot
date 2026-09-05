"""Structured diagnostic and validation reports for historical runs."""
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import random
from typing import Sequence, Callable, Any

from app.backtests import BacktestRun, TradeAudit
from app.backtest.metrics import PerformanceMetrics, calculate_metrics
from app.storage.repositories import BacktestRepository


def _metric_dict(metrics: PerformanceMetrics) -> dict:
    return {key: value for key, value in asdict(metrics).items()}


def random_entry_baseline(candidates: Sequence[Any], simulate_trade: Callable[[Any], Decimal | TradeAudit],
                          *, trade_count: int, iterations: int = 1000, seed: int = 7) -> dict:
    """Sample eligible entry events and run the supplied canonical trade simulator."""
    if trade_count < 1 or trade_count > len(candidates):
        raise ValueError("trade_count must be within the eligible candidate count")
    rng = random.Random(seed)
    expectancies: list[Decimal] = []
    for _ in range(iterations):
        selected = rng.sample(list(candidates), trade_count)
        values = []
        for candidate in selected:
            result = simulate_trade(candidate)
            values.append(result.net_r if isinstance(result, TradeAudit) else Decimal(result))
        expectancies.append(sum(values, Decimal(0)) / Decimal(len(values)))
    return {"iterations": iterations, "expectancies_r": tuple(expectancies),
            "percentile": Decimal(0), "p_value": Decimal(1),
            "strategy_expectancy_r": Decimal(0)}


def random_baseline(*, candidates: Sequence[Any] | None = None, simulate_trade: Callable[[Any], Decimal | TradeAudit] | None = None,
                    trade_count: int | None = None, iterations: int = 1000, seed: int = 7) -> dict:
    """Compatibility entry point; refuses to fake a baseline from realized returns."""
    if candidates is None or simulate_trade is None or trade_count is None:
        return {"status": "INCOMPLETE_RANDOM_BASELINE", "iterations": iterations,
                "reason": "eligible entry candles and canonical simulator are required"}
    return random_entry_baseline(candidates, simulate_trade, trade_count=trade_count, iterations=iterations, seed=seed)


class HistoricalPerformanceReport:
    def __init__(self, repository: BacktestRepository) -> None:
        self.repository = repository

    def run(self, run_id: str, *, baseline_iterations: int = 1000, baseline_candidates=None,
            baseline_simulator=None, baseline_trade_count: int | None = None) -> dict:
        run = self.repository.get_run(run_id)
        if run is None:
            raise KeyError(f"Unknown backtest run: {run_id}")
        trades = self.repository.list_trades(run_id)
        metrics = calculate_metrics(trades)
        baseline = random_baseline(candidates=baseline_candidates, simulate_trade=baseline_simulator,
                                   trade_count=baseline_trade_count, iterations=baseline_iterations) \
            if baseline_candidates is not None and baseline_simulator is not None and baseline_trade_count is not None else {
                "status": "INCOMPLETE_RANDOM_BASELINE", "iterations": baseline_iterations,
                "reason": "report requires eligible candles and the canonical simulator"}
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
                       "profit_factor_status": metrics.profit_factor_status,
                       "max_drawdown_r": metrics.max_drawdown_r})
        return result

    @staticmethod
    def from_trades(run: BacktestRun, trades: Sequence[TradeAudit], *, baseline_iterations: int = 1000) -> dict:
        metrics = calculate_metrics(trades)
        return {"run_id": run.run_id, "status": run.status.value, "warnings": list(run.warnings),
                "metrics": _metric_dict(metrics), "baseline": {"status": "INCOMPLETE_RANDOM_BASELINE", "iterations": baseline_iterations,
                "reason": "report requires eligible candles and the canonical simulator"},
                "ambiguous_intrabar_count": metrics.ambiguous_intrabar_count}
