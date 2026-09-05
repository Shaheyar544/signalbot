from dataclasses import asdict

from app.backtest.research import reproducibility_metadata
from app.backtest.research_scope import scoped_research_settings, validation_scope
from app.config.settings import load_settings


def test_eth_execution_scope_is_a_copy_and_leaves_default_configuration_untouched():
    settings = load_settings("tests/fixtures/settings.yaml")
    before = asdict(settings)
    scoped = scoped_research_settings(settings, ("ETHUSDT",))

    assert scoped.historical.symbols == ("ETHUSDT",)
    assert settings.historical.symbols == tuple(before["historical"]["symbols"])
    assert asdict(settings) == before
    assert scoped.primary_timeframe == settings.primary_timeframe
    assert scoped.confirmation_timeframes == settings.confirmation_timeframes
    assert scoped.swing == settings.swing and scoped.cost == settings.cost and scoped.exit_policy == settings.exit_policy


def test_eth_scope_identity_and_label_differ_from_multi_symbol_run(make_candle):
    settings = load_settings("tests/fixtures/settings.yaml")
    candles = {"ETHUSDT": [make_candle(symbol="ETHUSDT", offset=0)],
               "BTCUSDT": [make_candle(symbol="BTCUSDT", offset=0)]}
    full = reproducibility_metadata(settings, candles, random_seed=7, git_commit="same", validation_label="OFFICIAL_MULTI_SYMBOL_VALIDATION")
    eth_settings = scoped_research_settings(settings, ("ETHUSDT",))
    eth = reproducibility_metadata(eth_settings, {"ETHUSDT": candles["ETHUSDT"]}, random_seed=7,
                                   git_commit="same", validation_label="ETHUSDT_DIAGNOSTIC")

    assert full["research_run_id"] != eth["research_run_id"]
    assert eth["symbols"] == ["ETHUSDT"]
    assert eth["validation_label"] == "ETHUSDT_DIAGNOSTIC"
    assert validation_scope(("ETHUSDT",), "ETHUSDT_DIAGNOSTIC") == "ETHUSDT_DIAGNOSTIC"
    assert validation_scope(settings.historical.symbols, None) == "OFFICIAL_MULTI_SYMBOL_VALIDATION"
