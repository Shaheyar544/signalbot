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


def signal_evidence(assessment: SetupAssessment, risk: RiskAnalysis) -> dict[str, object]:
    """Serialize already-computed analysis facts for read-only explanation."""
    retest = assessment.retest
    setup = retest.setup
    csd = setup.source_csd
    confirmation = assessment.confirmation
    return {
        "structure": {"swing_kind": str(csd.broken_swing.kind), "swing_price": str(csd.broken_swing.price),
                      "swing_time": csd.broken_swing.candle_open_time.isoformat()},
        "csd": {"direction": str(csd.direction), "time": csd.candle.close_time.isoformat(),
                "close_distance_percent": str(csd.close_distance_percent)},
        "breakout": {"level": str(setup.breakout_level), "zone_lower": str(setup.zone_lower),
                     "zone_upper": str(setup.zone_upper), "status": str(setup.status), "quality": str(setup.quality)},
        "retest": {"time": retest.candle.close_time.isoformat(), "status": str(retest.status), "quality": str(retest.quality)},
        "confirmation": {"ema": confirmation.ema, "rsi": confirmation.rsi, "macd": confirmation.macd,
                         "volume": confirmation.volume, "one_hour": confirmation.one_hour, "four_hour": confirmation.four_hour},
        "score": {"total": str(assessment.score.total), "classification": str(assessment.score.classification),
                  "components": {key: str(value) for key, value in assessment.score.components.items()}},
        "risk": {"risk_unit": str(risk.risk_unit)},
    }


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
