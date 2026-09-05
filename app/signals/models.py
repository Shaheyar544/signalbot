from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from app.strategy.scoring import SignalClassification
from app.structure.csd import CSDDirection

if TYPE_CHECKING:
    from app.strategy.csd_strategy import SetupAssessment
    from app.strategy.risk import RiskAnalysis


def build_signal_id(assessment: SetupAssessment) -> str:
    setup = assessment.retest.setup
    swing = setup.source_csd.broken_swing
    return f"{setup.symbol}-{setup.timeframe}-{setup.direction}-{swing.candle_open_time.isoformat()}-{swing.price}"


@dataclass(frozen=True)
class SignalRecord:
    signal_id: str
    symbol: str
    timeframe: str
    direction: CSDDirection
    classification: SignalClassification
    confidence: Decimal
    entry_low: Decimal
    entry_high: Decimal
    reference_entry: Decimal
    stop_loss: Decimal
    take_profit_1: Decimal
    take_profit_2: Decimal
    take_profit_3: Decimal
    take_profit_4: Decimal | None
    created_at: datetime

    @classmethod
    def from_analysis(cls, assessment: SetupAssessment, risk: RiskAnalysis) -> "SignalRecord":
        return cls(build_signal_id(assessment), risk.symbol, risk.timeframe, risk.direction,
                   assessment.score.classification, assessment.score.total, risk.entry_low, risk.entry_high,
                   risk.reference_entry, risk.stop_loss, risk.take_profits[0], risk.take_profits[1],
                   risk.take_profits[2], risk.take_profit_4, assessment.retest.candle.close_time)
