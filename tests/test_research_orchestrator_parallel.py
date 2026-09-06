import asyncio
import pickle
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.backtest import research_orchestrator
from app.backtest.phase9 import build_symbol_validation
from app.backtest.research_orchestrator import UnifiedResearchOrchestrator, _run_symbol_validation_sync
from app.config.settings import load_settings


def _thread_executor(max_workers: int):
    return ThreadPoolExecutor(max_workers=max_workers)


def test_symbol_worker_inputs_are_picklable(make_candle):
    settings = load_settings("tests/fixtures/settings.yaml")
    payload = (settings, (make_candle(symbol="ETHUSDT"),), 1)

    assert pickle.loads(pickle.dumps(payload)) == payload


@pytest.mark.asyncio
async def test_parallel_symbol_baselines_match_sequential_results(make_candle):
    settings = load_settings("tests/fixtures/settings.yaml")
    inputs = {
        "ETHUSDT": (make_candle(symbol="ETHUSDT"),),
        "BTCUSDT": (make_candle(symbol="BTCUSDT"),),
    }
    sequential = {
        symbol: await build_symbol_validation(settings, candles, baseline_iterations=1)
        for symbol, candles in inputs.items()
    }
    runner = UnifiedResearchOrchestrator(settings, baseline_iterations=1, monte_carlo_iterations=1,
                                         executor_factory=_thread_executor)

    parallel = await runner._run_symbol_baselines(inputs, metadata={
        "git_commit": "test", "strategy_version": "v1", "configuration_hash": "config",
    }, checkpoint_store=None, update=lambda *_: None)

    assert parallel == sequential


@pytest.mark.asyncio
async def test_parallel_worker_failure_names_the_failed_symbol(make_candle, monkeypatch):
    settings = load_settings("tests/fixtures/settings.yaml")
    original = research_orchestrator._run_symbol_validation_sync

    def failing(settings, candles, baseline_iterations):
        if candles[0].symbol == "BTCUSDT":
            raise RuntimeError("simulated worker failure")
        return original(settings, candles, baseline_iterations)

    monkeypatch.setattr(research_orchestrator, "_run_symbol_validation_sync", failing)
    runner = UnifiedResearchOrchestrator(settings, baseline_iterations=1, monte_carlo_iterations=1,
                                         executor_factory=_thread_executor)
    with pytest.raises(RuntimeError, match="BTCUSDT.*simulated worker failure"):
        await runner._run_symbol_baselines({
            "ETHUSDT": (make_candle(symbol="ETHUSDT"),),
            "BTCUSDT": (make_candle(symbol="BTCUSDT"),),
        }, metadata={"git_commit": "test", "strategy_version": "v1", "configuration_hash": "config"},
           checkpoint_store=None, update=lambda *_: None)


@pytest.mark.asyncio
async def test_parallel_baselines_skip_completed_checkpointed_symbols(make_candle, tmp_path, monkeypatch):
    settings = load_settings("tests/fixtures/settings.yaml")
    inputs = {
        "ETHUSDT": (make_candle(symbol="ETHUSDT"),),
        "BTCUSDT": (make_candle(symbol="BTCUSDT"),),
    }
    calls = []
    original = research_orchestrator._run_symbol_validation_sync

    def counted(settings, candles, baseline_iterations):
        calls.append(candles[0].symbol)
        return original(settings, candles, baseline_iterations)

    monkeypatch.setattr(research_orchestrator, "_run_symbol_validation_sync", counted)
    runner = UnifiedResearchOrchestrator(settings, baseline_iterations=1, monte_carlo_iterations=1,
                                         executor_factory=_thread_executor)
    report = await runner.run(inputs, sensitivity_dimensions={"left_bars": [3]}, checkpoint_root=tmp_path,
                              checkpoint_mode="restart")
    assert calls == ["ETHUSDT", "BTCUSDT"]

    calls.clear()
    resumed = await runner.run(inputs, sensitivity_dimensions={"left_bars": [3]}, checkpoint_root=tmp_path,
                               checkpoint_mode="resume")
    assert calls == []
    assert report["baseline"] == resumed["baseline"]
