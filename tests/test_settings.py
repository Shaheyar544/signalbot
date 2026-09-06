from pathlib import Path
from decimal import Decimal

import pytest

from app.config.settings import load_settings, normalize_symbol


def test_loads_enabled_disabled_multiple_symbols():
    config = Path(__file__).parent / "fixtures" / "settings.yaml"
    settings = load_settings(config)
    assert settings.enabled_symbols == ("ETHUSDT",)
    assert settings.timeframes == ("15m", "1h", "4h")
    assert settings.historical_candle_limit == 42
    assert settings.swing.left_bars == 3
    assert settings.csd.minimum_close_distance_percent == Decimal("0.05")
    assert settings.breakout.method == "percent"
    assert settings.breakout.minimum_close_atr == Decimal("0.15")
    assert settings.regime.high_atr_percent == Decimal("1.5")
    assert settings.retest.maximum_bars_after_breakout == 12
    assert settings.confirmation.volume_ratio_minimum == Decimal("1")
    assert settings.risk.stop_buffer_percent == Decimal("0")


@pytest.mark.parametrize(("raw", "expected"), [("ethusdt", "ETHUSDT"), ("ETH/USDT", "ETHUSDT")])
def test_normalizes_symbols(raw, expected):
    assert normalize_symbol(raw) == expected


def test_rejects_invalid_symbol():
    with pytest.raises(ValueError):
        normalize_symbol("INVALID PAIR!")


def test_loader_skips_invalid_symbol_instead_of_stopping_other_pairs():
    config = Path(__file__).parent / "fixtures" / "invalid-symbol-settings.yaml"
    settings = load_settings(config)
    assert settings.enabled_symbols == ("ETHUSDT",)
    assert settings.invalid_symbols == ("BAD!",)


def test_production_configuration_includes_one_day_confirmation_and_history():
    settings = load_settings("config.yaml")

    assert settings.confirmation_timeframes == ("1h", "4h", "1d")
    assert settings.timeframes == ("15m", "1h", "4h", "1d")
    assert settings.historical.timeframes == ("15m", "1h", "4h", "1d")
