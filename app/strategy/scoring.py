from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.strategy.confirmation import ConfirmationResult


_MAX_WEIGHTED_TOTAL = Decimal("12")


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


@dataclass(frozen=True)
class ScoringWeights:
    csd: Decimal = Decimal("2.0")
    breakout: Decimal = Decimal("2.0")
    retest: Decimal = Decimal("2.0")
    ema: Decimal = Decimal("1.5")
    rsi: Decimal = Decimal("1.0")
    macd: Decimal = Decimal("1.0")
    volume: Decimal = Decimal("1.0")
    htf: Decimal = Decimal("1.5")


class ScoringEngine:
    # TODO: recalibrate thresholds from validation report.
    def __init__(self, weights: ScoringWeights | None = None,
                 threshold_watch: Decimal = Decimal("3.0"),
                 threshold_good: Decimal = Decimal("5.0"),
                 threshold_strong: Decimal = Decimal("7.5")) -> None:
        self.weights = weights or ScoringWeights()
        self.threshold_watch = threshold_watch
        self.threshold_good = threshold_good
        self.threshold_strong = threshold_strong

    def score(self, confirmation: ConfirmationResult, *, csd_quality: Decimal, breakout_quality: Decimal, retest_quality: Decimal) -> ConfidenceScore:
        qualities = {
            "csd": csd_quality, "breakout": breakout_quality, "retest": retest_quality,
            "ema": confirmation.ema_quality, "rsi": confirmation.rsi_quality,
            "macd": confirmation.macd_quality, "volume": confirmation.volume_quality,
            "htf": confirmation.htf_quality,
        }
        if any(not Decimal(0) <= quality <= Decimal(1) for quality in qualities.values()):
            raise ValueError("quality values must be in [0, 1]")
        weight_values = self.weights.__dict__
        components = {name: quality * weight_values[name] * Decimal(10) / _MAX_WEIGHTED_TOTAL for name, quality in qualities.items()}
        total = sum(components.values())
        if total < self.threshold_watch:
            classification = SignalClassification.NO_TRADE
        elif total < self.threshold_good:
            classification = SignalClassification.WATCH
        elif total < self.threshold_strong:
            classification = SignalClassification.GOOD_SIGNAL
        else:
            classification = SignalClassification.STRONG_SIGNAL
        return ConfidenceScore(total, components, classification)
