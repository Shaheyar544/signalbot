from datetime import datetime, timezone
import pytest

from app.backtest.research_checkpoints import ResearchCheckpointStore, ResearchProgress, atomic_json_write
from app.backtest.research_orchestrator import UnifiedResearchOrchestrator


def _identity(**overrides):
    value = {"research_run_id": "run-1", "git_commit": "abc", "configuration_hash": "config",
             "methodology_id": "phase9", "random_seed": 7, "dataset_identity": "dataset"}
    value.update(overrides)
    return value


def test_checkpoint_is_resumable_only_for_exact_identity(tmp_path):
    first = ResearchCheckpointStore(tmp_path, _identity(), mode="restart")
    first.save("baseline", {"symbol": "ETHUSDT"}, {"audits": ["immutable"]})
    assert ResearchCheckpointStore(tmp_path, _identity(), mode="resume").load("baseline", {"symbol": "ETHUSDT"}) == {"audits": ["immutable"]}
    assert ResearchCheckpointStore(tmp_path, _identity(random_seed=8), mode="resume").load("baseline", {"symbol": "ETHUSDT"}) is None
    assert ResearchCheckpointStore(tmp_path, _identity(git_commit="changed"), mode="resume").load("baseline", {"symbol": "ETHUSDT"}) is None


def test_restart_discards_only_the_exact_run_checkpoint_directory(tmp_path):
    store = ResearchCheckpointStore(tmp_path, _identity(), mode="restart")
    store.save("baseline", {}, "old")
    restarted = ResearchCheckpointStore(tmp_path, _identity(), mode="restart")
    assert restarted.load("baseline", {}) is None


def test_progress_and_partial_json_are_atomic_and_explicit(tmp_path):
    path = tmp_path / "research_progress.json"
    progress = ResearchProgress(path, _identity(), 4)
    value = progress.update("baseline", completed_units=1, cache_hits=2, cache_misses=1, replay_count=1)
    assert value["status"] == "RUNNING"
    assert value["progress_percent"] == 25
    assert path.exists()
    atomic_json_write(tmp_path / "partial.json", {"status": "RUNNING", "updated_at": datetime.now(timezone.utc)})
    assert '"status": "RUNNING"' in (tmp_path / "partial.json").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_clean_and_resumed_small_research_fixture_are_numerically_equivalent(tmp_path):
    from app.config.settings import load_settings
    settings = load_settings("tests/fixtures/settings.yaml")
    clean = await UnifiedResearchOrchestrator(settings, baseline_iterations=1, monte_carlo_iterations=1).run(
        {"ETHUSDT": ()}, sensitivity_dimensions={"left_bars": [3]})
    resumed = await UnifiedResearchOrchestrator(settings, baseline_iterations=1, monte_carlo_iterations=1).run(
        {"ETHUSDT": ()}, sensitivity_dimensions={"left_bars": [3]}, checkpoint_root=tmp_path,
        checkpoint_mode="restart", progress_path=tmp_path / "progress.json")
    resumed_again = await UnifiedResearchOrchestrator(settings, baseline_iterations=1, monte_carlo_iterations=1).run(
        {"ETHUSDT": ()}, sensitivity_dimensions={"left_bars": [3]}, checkpoint_root=tmp_path,
        checkpoint_mode="resume")
    for field in ("baseline", "walk_forward", "sensitivity", "htf_experiment", "monte_carlo", "leave_one_symbol_out", "cost_stress"):
        assert clean[field] == resumed[field] == resumed_again[field]
    assert (tmp_path / "progress.json").exists()


@pytest.mark.asyncio
async def test_interrupted_then_resumed_fixture_matches_clean_run(tmp_path, monkeypatch):
    """The first completed symbol is durable before an independent failure."""
    from app.backtest import research_orchestrator
    from app.config.settings import load_settings
    settings = load_settings("tests/fixtures/settings.yaml")
    inputs = {"ETHUSDT": (), "BTCUSDT": ()}
    clean = await UnifiedResearchOrchestrator(settings, baseline_iterations=1, monte_carlo_iterations=1).run(
        inputs, sensitivity_dimensions={"left_bars": [3]})
    original = research_orchestrator.build_symbol_validation
    calls = 0
    async def interrupted(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated interruption")
        return await original(*args, **kwargs)
    monkeypatch.setattr(research_orchestrator, "build_symbol_validation", interrupted)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        await UnifiedResearchOrchestrator(settings, baseline_iterations=1, monte_carlo_iterations=1).run(
            inputs, sensitivity_dimensions={"left_bars": [3]}, checkpoint_root=tmp_path, checkpoint_mode="restart")
    monkeypatch.setattr(research_orchestrator, "build_symbol_validation", original)
    resumed = await UnifiedResearchOrchestrator(settings, baseline_iterations=1, monte_carlo_iterations=1).run(
        inputs, sensitivity_dimensions={"left_bars": [3]}, checkpoint_root=tmp_path, checkpoint_mode="resume")
    for field in ("baseline", "walk_forward", "sensitivity", "htf_experiment", "monte_carlo", "leave_one_symbol_out", "cost_stress"):
        assert clean[field] == resumed[field]
