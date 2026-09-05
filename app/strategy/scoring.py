from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.strategy.confirmation import ConfirmationResult


class SignalClassification(StrEnum):
    NO_TRADE = "NO_TRADE"
    WATCH = "WATCH"
    GOOD_SIGNAL = "GOOD_SIGNAL"
    STRONG_SIGNAL = "STRONG_SIGNAL"


@dataclass(frozen=True)
class ConfidenceScore:
    total: Decimal
    components: dict[str, Decimal]
    classification: SignalClassification


class ScoringEngine:
    # TODO: recalibrate thresholds from validation report.
    def score(self, confirmation: ConfirmationResult, *, csd_quality: Decimal, breakout_quality: Decimal, retest_quality: Decimal) -> ConfidenceScore:
        raw = {"csd": csd_quality*2, "breakout": breakout_quality*2, "retest": retest_quality*2, "ema": confirmation.ema_quality*Decimal("1.5"), "rsi": confirmation.rsi_quality, "macd": confirmation.macd_quality, "volume": confirmation.volume_quality, "htf": confirmation.htf_quality*Decimal("1.5")}
        total = sum(raw.values()) * Decimal(10) / Decimal(12)
        if total < Decimal("3"):
            classification = SignalClassification.NO_TRADE
        elif total < Decimal("5"):
            classification = SignalClassification.WATCH
        elif total < Decimal("7.5"):
            classification = SignalClassification.GOOD_SIGNAL
        else:
            classification = SignalClassification.STRONG_SIGNAL
        return ConfidenceScore(total, raw, classification)
