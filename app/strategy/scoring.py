from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.strategy.confirmation import ConfirmationResult


class SignalClassification(StrEnum):
    NO_TRADE = "NO_TRADE"
    WATCH = "WATCH"
    CONFIRMATION_PENDING = "CONFIRMATION_PENDING"


@dataclass(frozen=True)
class ConfidenceScore:
    setup_valid: bool
    confluence_score: int
    classification: SignalClassification


class ScoringEngine:
    def score(self, confirmation: ConfirmationResult, *, has_csd: bool, has_breakout: bool, has_retest: bool) -> ConfidenceScore:
        setup_valid = has_csd and has_breakout and has_retest
        confluence_score = int(confirmation.ema) + int(confirmation.rsi) + int(confirmation.macd) + int(confirmation.volume)
        if not setup_valid:
            classification = SignalClassification.NO_TRADE
        elif confluence_score == 0:
            classification = SignalClassification.WATCH
        else:
            classification = SignalClassification.CONFIRMATION_PENDING
        return ConfidenceScore(setup_valid, confluence_score, classification)
