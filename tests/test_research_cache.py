from app.backtest.research_cache import ResearchReplayCache, replay_cache_key


def test_research_cache_reuses_only_an_identical_full_identity():
    cache = ResearchReplayCache()
    key = replay_cache_key(git_commit="abc", strategy_version="v1", configuration_hash="cfg", symbol="ETHUSDT",
                           timeframes=("15m", "1h", "4h"), start="2024-01-01", end="2024-02-01", variant="base")
    calls = []
    assert cache.get_or_compute(key, lambda: calls.append("run") or {"audit": 1}) == {"audit": 1}
    assert cache.get_or_compute(key, lambda: calls.append("unexpected") or {}) == {"audit": 1}
    assert calls == ["run"]
    assert cache.stats == {"hits": 1, "misses": 1}


def test_research_cache_key_changes_when_any_result_defining_input_changes():
    base = dict(git_commit="abc", strategy_version="v1", configuration_hash="cfg", symbol="ETHUSDT",
                timeframes=("15m",), start="2024-01-01", end="2024-02-01", variant="base")
    key = replay_cache_key(**base)
    assert replay_cache_key(**{**base, "variant": "15m-only"}) != key
    assert replay_cache_key(**{**base, "configuration_hash": "other"}) != key
    assert replay_cache_key(**{**base, "git_commit": "def"}) != key
