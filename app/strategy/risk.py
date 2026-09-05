from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Sequence

from app.structure.csd import CSDDirection
from app.structure.market_structure import StructureEvent
from app.structure.swings import SwingType

if TYPE_CHECKING:
    from app.strategy.csd_strategy import SetupAssessment


@dataclass(frozen=True)
class RiskAnalysis:
    symbol: str
    timeframe: str
    direction: CSDDirection
    entry_low: Decimal
    entry_high: Decimal
    reference_entry: Decimal
    stop_loss: Decimal
    risk_unit: Decimal
    take_profits: tuple[Decimal, Decimal, Decimal]
    take_profit_4: Decimal | None


class RiskEngine:
    """Derives informational risk reference values from a validated setup."""
    def __init__(self, stop_buffer_percent: Decimal = Decimal("0")) -> None:
        if stop_buffer_percent < 0:
            raise ValueError("stop_buffer_percent cannot be negative")
        self.stop_buffer_percent = stop_buffer_percent

    def calculate(self, assessment: SetupAssessment, structure_events: Sequence[StructureEvent] = ()) -> RiskAnalysis:
        setup = assessment.retest.setup
        retest_candle = assessment.retest.candle
        reference_entry = (setup.zone_lower + setup.zone_upper) / Decimal(2)
        if setup.direction is CSDDirection.BULLISH:
            anchor = min(retest_candle.low, setup.source_csd.candle.low)
            stop_loss = anchor * (Decimal(1) - self.stop_buffer_percent / Decimal(100))
            risk = reference_entry - stop_loss
            targets = tuple(reference_entry + risk * multiple for multiple in (1, 2, 3))
        else:
            anchor = max(retest_candle.high, setup.source_csd.candle.high)
            stop_loss = anchor * (Decimal(1) + self.stop_buffer_percent / Decimal(100))
            risk = stop_loss - reference_entry
            targets = tuple(reference_entry - risk * multiple for multiple in (1, 2, 3))
        if risk <= 0:
            raise ValueError("Risk calculation requires a stop loss beyond the entry zone")
        tp4 = self._structure_target(setup.direction, reference_entry, setup.symbol, setup.timeframe, structure_events)
        return RiskAnalysis(setup.symbol, setup.timeframe, setup.direction, setup.zone_lower, setup.zone_upper,
                            reference_entry, stop_loss, risk, targets, tp4)  # type: ignore[arg-type]

    @staticmethod
    def _structure_target(direction: CSDDirection, entry: Decimal, symbol: str, timeframe: str,
                          events: Sequence[StructureEvent]) -> Decimal | None:
        relevant = [event for event in events if (event.symbol, event.timeframe) == (symbol, timeframe)]
        if direction is CSDDirection.BULLISH:
            candidates = [event.swing.price for event in relevant if event.swing.kind is SwingType.HIGH and event.swing.price > entry]
            return min(candidates) if candidates else None
        candidates = [event.swing.price for event in relevant if event.swing.kind is SwingType.LOW and event.swing.price < entry]
        return max(candidates) if candidates else None
