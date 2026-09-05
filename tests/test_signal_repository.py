from decimal import Decimal
from pathlib import Path

from app.signals.models import build_signal_id
from app.storage.database import Database
from app.storage.repositories import SignalRepository
from app.strategy.breakout import BreakoutSetup, BreakoutStatus
from app.strategy.confirmation import ConfirmationResult
from app.strategy.csd_strategy import SetupAssessment
from app.strategy.retest import RetestEvent
from app.strategy.risk import RiskAnalysis
from app.strategy.scoring import ConfidenceScore, SignalClassification
from app.structure.csd import CSDEvent, CSDDirection
from app.structure.swings import SwingPoint, SwingType


def _record_inputs(make_candle):
    source = make_candle(offset=0, close="101")
    retest_candle = make_candle(offset=1, close="100.1")
    level = Decimal("100")
    swing = SwingPoint(source.symbol, source.timeframe, source.open_time, level, SwingType.HIGH, source)
    csd = CSDEvent(source.symbol, source.timeframe, CSDDirection.BULLISH, source, swing, Decimal("1"))
    setup = BreakoutSetup(source.symbol, source.timeframe, CSDDirection.BULLISH, level, Decimal("99.8"), Decimal("100.2"), csd, BreakoutStatus.RETEST_DETECTED)
    retest = RetestEvent(source.symbol, source.timeframe, retest_candle, level, BreakoutStatus.RETEST_DETECTED, setup)
    assessment = SetupAssessment(retest, ConfirmationResult(CSDDirection.BULLISH, True, True, True, True, True, True), ConfidenceScore(True, 4, SignalClassification.CONFIRMATION_PENDING))
    risk = RiskAnalysis(source.symbol, source.timeframe, CSDDirection.BULLISH, Decimal("99.8"), Decimal("100.2"), Decimal("100"), Decimal("99"), Decimal("1"), (Decimal("101"), Decimal("102"), Decimal("103")), Decimal("105"))
    return assessment, risk


def test_signal_repository_persists_and_retrieves_stable_record(make_candle):
    database = Database(Path(":memory:")); database.open()
    assessment, risk = _record_inputs(make_candle)
    repository = SignalRepository(database)

    assert repository.save(assessment, risk)
    signal_id = build_signal_id(assessment)
    record = repository.get(signal_id)

    assert record is not None
    assert record.signal_id == signal_id
    assert record.reference_entry == Decimal("100")
    assert record.take_profit_4 == Decimal("105")
    database.close()


def test_signal_repository_rejects_duplicate_stable_id(make_candle):
    database = Database(Path(":memory:")); database.open()
    assessment, risk = _record_inputs(make_candle)
    repository = SignalRepository(database)

    assert repository.save(assessment, risk)
    assert not repository.save(assessment, risk)
    database.close()
