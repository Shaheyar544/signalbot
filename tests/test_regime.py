from decimal import Decimal

from app.indicators.engine import IndicatorValues
from app.strategy.regime import MarketRegime, RegimeClassifier


def values(*, ema10: str, ema50: str, atr: str | None) -> IndicatorValues:
    return IndicatorValues(ema={10: Decimal(ema10), 50: Decimal(ema50)}, atr=Decimal(atr) if atr else None)


def test_regime_classifier_identifies_trend_direction_before_neutral_states():
    classifier = RegimeClassifier(trend_ema_separation_percent=Decimal("0.2"))

    assert classifier.classify(Decimal("101"), values(ema10="101", ema50="100", atr="1")) is MarketRegime.TREND_UP
    assert classifier.classify(Decimal("99"), values(ema10="99", ema50="100", atr="1")) is MarketRegime.TREND_DOWN


def test_regime_classifier_identifies_high_and_low_volatility_deterministically():
    classifier = RegimeClassifier(high_atr_percent=Decimal("1.5"), low_atr_percent=Decimal("0.3"))

    assert classifier.classify(Decimal("100"), values(ema10="100", ema50="100", atr="2")) is MarketRegime.HIGH_VOLATILITY
    assert classifier.classify(Decimal("100"), values(ema10="100", ema50="100", atr="0.2")) is MarketRegime.LOW_VOLATILITY


def test_regime_classifier_distinguishes_range_and_transition():
    classifier = RegimeClassifier(trend_ema_separation_percent=Decimal("0.2"), range_ema_separation_percent=Decimal("0.05"))

    assert classifier.classify(Decimal("100"), values(ema10="100.01", ema50="100", atr="0.8")) is MarketRegime.RANGE
    assert classifier.classify(Decimal("100"), values(ema10="100.1", ema50="100", atr="0.8")) is MarketRegime.TRANSITION
