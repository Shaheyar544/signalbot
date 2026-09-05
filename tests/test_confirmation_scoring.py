from decimal import Decimal

from app.indicators.engine import IndicatorValues, MacdValues
from app.strategy.confirmation import ConfirmationEngine
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


def test_scoring_engine_separates_valid_setup_from_four_point_confluence():
    confirmation = ConfirmationEngine().evaluate(CSDDirection.BULLISH, _indicators(), _indicators(), _indicators())

    score = ScoringEngine().score(confirmation, has_csd=True, has_breakout=True, has_retest=True)

    assert score.setup_valid is True
    assert score.confluence_score == 4
    assert score.classification is SignalClassification.CONFIRMATION_PENDING


def test_scoring_engine_classifies_required_setup_without_support_as_watch():
    confirmation = ConfirmationEngine().evaluate(CSDDirection.BULLISH, _indicators(ema_fast="90", ema_slow="100", rsi="40", histogram="-1", volume_ratio="0.5"), None, None)

    score = ScoringEngine().score(confirmation, has_csd=True, has_breakout=True, has_retest=True)

    assert score.setup_valid is True
    assert score.confluence_score == 0
    assert score.classification is SignalClassification.WATCH
