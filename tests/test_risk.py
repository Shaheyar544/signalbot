from decimal import Decimal

from app.strategy.breakout import BreakoutSetup, BreakoutStatus
from app.strategy.confirmation import ConfirmationResult
from app.strategy.csd_strategy import SetupAssessment
from app.strategy.retest import RetestEvent
from app.strategy.risk import RiskEngine
from app.strategy.scoring import ConfidenceScore, SignalClassification
from app.structure.csd import CSDEvent, CSDDirection
from app.structure.swings import SwingPoint, SwingType
from app.structure.market_structure import StructureEvent, StructureKind


def _assessment(make_candle, direction=CSDDirection.BULLISH):
    source = make_candle(offset=0, close="101")
    retest_candle = make_candle(offset=1, close="100.1")
    level = Decimal("100")
    swing = SwingPoint(source.symbol, source.timeframe, source.open_time, level, SwingType.HIGH if direction is CSDDirection.BULLISH else SwingType.LOW, source)
    csd = CSDEvent(source.symbol, source.timeframe, direction, source, swing, Decimal("1"))
    setup = BreakoutSetup(source.symbol, source.timeframe, direction, level, Decimal("99.8"), Decimal("100.2"), csd, BreakoutStatus.RETEST_DETECTED)
    retest = RetestEvent(source.symbol, source.timeframe, retest_candle, level, BreakoutStatus.RETEST_DETECTED, setup)
    confirmation = ConfirmationResult(direction, True, True, True, True, True, True)
    return SetupAssessment(retest, confirmation, ConfidenceScore(Decimal("8"), {}, SignalClassification.STRONG_SIGNAL))


def test_risk_engine_calculates_bullish_retest_zone_stop_targets_and_risk(make_candle):
    analysis = RiskEngine(stop_buffer_percent=Decimal("0")).calculate(_assessment(make_candle))

    assert analysis.entry_low == Decimal("99.8")
    assert analysis.entry_high == Decimal("100.2")
    assert analysis.reference_entry == Decimal("100")
    assert analysis.stop_loss == Decimal("99")
    assert analysis.take_profits == (Decimal("101"), Decimal("102"), Decimal("103"))
    assert analysis.risk_unit == Decimal("1")


def test_risk_engine_mirrors_bearish_targets(make_candle):
    analysis = RiskEngine(stop_buffer_percent=Decimal("0")).calculate(_assessment(make_candle, CSDDirection.BEARISH))

    assert analysis.stop_loss == Decimal("102")
    assert analysis.take_profits == (Decimal("98"), Decimal("96"), Decimal("94"))


def test_risk_engine_uses_nearest_opposing_structure_as_optional_tp4(make_candle):
    assessment = _assessment(make_candle)
    source = assessment.retest.setup.source_csd.candle
    near = SwingPoint(source.symbol, source.timeframe, source.open_time, Decimal("105"), SwingType.HIGH, source)
    far = SwingPoint(source.symbol, source.timeframe, source.open_time, Decimal("110"), SwingType.HIGH, source)
    structure = [
        StructureEvent(source.symbol, source.timeframe, far, StructureKind.HH),
        StructureEvent(source.symbol, source.timeframe, near, StructureKind.HH),
    ]

    analysis = RiskEngine().calculate(assessment, structure)

    assert analysis.take_profit_4 == Decimal("105")


def test_risk_engine_leaves_tp4_empty_without_opposing_structure(make_candle):
    analysis = RiskEngine().calculate(_assessment(make_candle), [])

    assert analysis.take_profit_4 is None
