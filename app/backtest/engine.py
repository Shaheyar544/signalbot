"""Public backtest composition seam."""
from __future__ import annotations

from app.backtest.report import HistoricalPerformanceReport
from app.backtest_runner import HistoricalBacktestRunner


class BacktestEngine:
    def __init__(self, runner: HistoricalBacktestRunner, report: HistoricalPerformanceReport) -> None:
        self.runner = runner
        self.report = report

    async def run(self, candles):
        run = await self.runner.run(candles)
        return self.report.run(run.run_id)
