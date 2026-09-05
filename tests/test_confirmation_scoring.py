from decimal import Decimal

from app.indicators.engine import IndicatorValues, MacdValues
from app.strategy.confirmation import ConfirmationEngine, ConfirmationResult
from app.strategy.scoring import ScoringEngine, SignalClassification
from app.structure.csd import CSDDirection


def _indicators(*, ema_fast="110", ema_slow="100", rsi="55", histogram="1", volume_ratio="1.5"):
    return IndicatorValues(
        ema={10: Decimal(ema_fast), 50: Decimal(ema_slow)},
        rsi=Decimal(rsi),
        macd=MacdValues(Decimal("1"), Decimal("0"), Decimal(histogram)),
        volume_ratio=Decimal(volume_ratio),
    )


def test_confirmation_engine_reports_bullish_primary_and_higher_timeframe_evidence():
    indicators = _indicators()

    result = ConfirmationEngine().evaluate(CSDDirection.BULLISH, indicators, indicators, indicators)

    assert result.ema and result.rsi and result.macd and result.volume
    assert result.one_hour and result.four_hour


def test_confirmation_engine_mirrors_bearish_conditions():
    bearish = _indicators(ema_fast="90", ema_slow="100", rsi="45", histogram="-1", volume_ratio="1.2")

    result = ConfirmationEngine().evaluate(CSDDirection.BEARISH, bearish, bearish, bearish)

    assert all((result.ema, result.rsi, result.macd, result.volume, result.one_hour, result.four_hour))


def test_scoring_engine_uses_continuous_quality_components_for_strong_setup():
    confirmation = ConfirmationEngine().evaluate(CSDDirection.BULLISH, _indicators(), _indicators(), _indicators())

    score = ScoringEngine().score(confirmation, csd_quality=Decimal("1"), breakout_quality=Decimal("1"), retest_quality=Decimal("1"))

    assert Decimal("7.5") <= score.total <= Decimal("10")
    assert score.classification is SignalClassification.STRONG_SIGNAL


def test_scoring_engine_reaches_watch_for_medium_quality_setup():
    confirmation = ConfirmationEngine().evaluate(CSDDirection.BULLISH, _indicators(ema_fast="90", ema_slow="100", rsi="40", histogram="-1", volume_ratio="0.5"), None, None)

    score = ScoringEngine().score(confirmation, csd_quality=Decimal("0.6"), breakout_quality=Decimal("0.6"), retest_quality=Decimal("0.6"))

    assert score.classification is SignalClassification.WATCH


def test_scoring_boundaries_make_every_classification_reachable():
    confirmation = ConfirmationResult(
        CSDDirection.BULLISH, False, False, False, False, False, False,
        Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"),
    )
    engine = ScoringEngine()

    assert engine.score(confirmation, csd_quality=Decimal("0"), breakout_quality=Decimal("0"), retest_quality=Decimal("0")).classification is SignalClassification.NO_TRADE
    assert engine.score(confirmation, csd_quality=Decimal("0.9"), breakout_quality=Decimal("0.9"), retest_quality=Decimal("0")).classification is SignalClassification.WATCH
    assert engine.score(confirmation, csd_quality=Decimal("1"), breakout_quality=Decimal("1"), retest_quality=Decimal("1")).classification is SignalClassification.GOOD_SIGNAL

    strong_confirmation = ConfirmationResult(
        CSDDirection.BULLISH, True, False, False, False, True, True,
        Decimal("1"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("1"),
    )
    assert engine.score(strong_confirmation, csd_quality=Decimal("1"), breakout_quality=Decimal("1"), retest_quality=Decimal("1")).classification is SignalClassification.STRONG_SIGNAL
