from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.strategy.confirmation import ConfirmationResult


_MAX_WEIGHTED_TOTAL = Decimal("12")
# These are the frozen implementation thresholds used for historical replay,
# live classification, signal eligibility, and all reports.  Earlier prose
# describing 0–4/5–6/7–8/9–10 bands predates graded V1 scoring and is not the
# executable V1 contract.
FROZEN_V1_SCORE_BANDS = {
    "NO_TRADE": (Decimal("0"), Decimal("3.0")),
    "WATCH": (Decimal("3.0"), Decimal("5.0")),
    "GOOD_SIGNAL": (Decimal("5.0"), Decimal("7.5")),
    "STRONG_SIGNAL": (Decimal("7.5"), Decimal("10")),
}


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
                 threshold_watch: Decimal = FROZEN_V1_SCORE_BANDS["WATCH"][0],
                 threshold_good: Decimal = FROZEN_V1_SCORE_BANDS["GOOD_SIGNAL"][0],
                 threshold_strong: Decimal = FROZEN_V1_SCORE_BANDS["STRONG_SIGNAL"][0]) -> None:
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


def frozen_v1_score_semantics() -> dict[str, object]:
    """Machine-readable canonical reporting contract; no strategy tuning."""
    return {"bands": {name: {"minimum_inclusive": low, "maximum_exclusive": high}
                      for name, (low, high) in FROZEN_V1_SCORE_BANDS.items()},
            "eligible_classifications": (SignalClassification.GOOD_SIGNAL, SignalClassification.STRONG_SIGNAL)}
