from decimal import Decimal

from app.indicators.engine import IndicatorValues, MacdValues
from app.strategy.confirmation import ConfirmationEngine, ConfirmationResult
from app.strategy.scoring import ScoringEngine, SignalClassification, frozen_v1_score_semantics
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

    result = ConfirmationEngine().evaluate(CSDDirection.BULLISH, indicators, {"1h": indicators, "4h": indicators})

    assert result.ema and result.rsi and result.macd and result.volume
    assert result.higher_timeframes == {"1h": True, "4h": True}


def test_confirmation_engine_mirrors_bearish_conditions():
    bearish = _indicators(ema_fast="90", ema_slow="100", rsi="45", histogram="-1", volume_ratio="1.2")

    result = ConfirmationEngine().evaluate(CSDDirection.BEARISH, bearish, {"1h": bearish, "4h": bearish})

    assert all((result.ema, result.rsi, result.macd, result.volume))
    assert result.higher_timeframes == {"1h": True, "4h": True}


def test_scoring_engine_uses_continuous_quality_components_for_strong_setup():
    confirmation = ConfirmationEngine().evaluate(CSDDirection.BULLISH, _indicators(), {"1h": _indicators(), "4h": _indicators()})

    score = ScoringEngine().score(confirmation, csd_quality=Decimal("1"), breakout_quality=Decimal("1"), retest_quality=Decimal("1"))

    assert Decimal("7.5") <= score.total <= Decimal("10")
    assert score.classification is SignalClassification.STRONG_SIGNAL


def test_scoring_engine_reaches_watch_for_medium_quality_setup():
    confirmation = ConfirmationEngine().evaluate(CSDDirection.BULLISH, _indicators(ema_fast="90", ema_slow="100", rsi="40", histogram="-1", volume_ratio="0.5"), {"1h": None, "4h": None})

    score = ScoringEngine().score(confirmation, csd_quality=Decimal("0.6"), breakout_quality=Decimal("0.6"), retest_quality=Decimal("0.6"))

    assert score.classification is SignalClassification.WATCH


def test_scoring_boundaries_make_every_classification_reachable():
    confirmation = ConfirmationResult(
        CSDDirection.BULLISH, False, False, False, False, {},
        Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"),
    )
    engine = ScoringEngine()

    assert engine.score(confirmation, csd_quality=Decimal("0"), breakout_quality=Decimal("0"), retest_quality=Decimal("0")).classification is SignalClassification.NO_TRADE
    assert engine.score(confirmation, csd_quality=Decimal("0.9"), breakout_quality=Decimal("0.9"), retest_quality=Decimal("0")).classification is SignalClassification.WATCH
    assert engine.score(confirmation, csd_quality=Decimal("1"), breakout_quality=Decimal("1"), retest_quality=Decimal("1")).classification is SignalClassification.GOOD_SIGNAL

    strong_confirmation = ConfirmationResult(
        CSDDirection.BULLISH, True, False, False, False, {"1h": True, "4h": True},
        Decimal("1"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("1"),
    )
    assert engine.score(strong_confirmation, csd_quality=Decimal("1"), breakout_quality=Decimal("1"), retest_quality=Decimal("1")).classification is SignalClassification.STRONG_SIGNAL


def test_frozen_v1_score_semantics_match_executable_classification_thresholds():
    semantics = frozen_v1_score_semantics()
    assert semantics["bands"]["WATCH"]["minimum_inclusive"] == Decimal("3.0")
    assert semantics["bands"]["GOOD_SIGNAL"]["minimum_inclusive"] == Decimal("5.0")
    assert semantics["bands"]["STRONG_SIGNAL"]["minimum_inclusive"] == Decimal("7.5")
    assert tuple(semantics["eligible_classifications"]) == (SignalClassification.GOOD_SIGNAL, SignalClassification.STRONG_SIGNAL)


def test_confirmation_engine_calculates_exact_three_timeframe_agreement_fractions():
    aligned = _indicators()
    opposed = _indicators(ema_fast="90", ema_slow="100")
    engine = ConfirmationEngine()

    assert engine.evaluate(CSDDirection.BULLISH, aligned, {"1h": aligned, "4h": aligned, "1d": aligned}).htf_quality == Decimal("1")
    assert engine.evaluate(CSDDirection.BULLISH, aligned, {"1h": aligned, "4h": aligned, "1d": opposed}).htf_quality == Decimal("2") / Decimal("3")
    assert engine.evaluate(CSDDirection.BULLISH, aligned, {"1h": aligned, "4h": opposed, "1d": opposed}).htf_quality == Decimal("1") / Decimal("3")
    assert engine.evaluate(CSDDirection.BULLISH, aligned, {"1h": opposed, "4h": opposed, "1d": opposed}).htf_quality == Decimal("0")


def test_confirmation_engine_empty_higher_timeframes_is_safe_and_has_zero_quality():
    result = ConfirmationEngine().evaluate(CSDDirection.BULLISH, _indicators(), {})

    assert result.higher_timeframes == {}
    assert result.htf_quality == Decimal("0")
