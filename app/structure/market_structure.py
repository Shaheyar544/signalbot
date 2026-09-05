from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Sequence

from app.structure.swings import SwingPoint, SwingType


class StructureKind(StrEnum):
    HH = "HH"
    HL = "HL"
    LH = "LH"
    LL = "LL"


@dataclass(frozen=True)
class StructureEvent:
    symbol: str
    timeframe: str
    swing: SwingPoint
    kind: StructureKind | None


class MarketStructureEngine:
    """Classifies each swing against the preceding swing of the same type."""
    def evaluate(self, symbol: str, timeframe: str, swings: Sequence[SwingPoint]) -> list[StructureEvent]:
        previous_by_type: dict[SwingType, SwingPoint] = {}
        events: list[StructureEvent] = []
        for swing in sorted(swings, key=lambda item: item.candle_open_time):
            if (swing.symbol, swing.timeframe) != (symbol, timeframe):
                raise ValueError("All swings must belong to the requested symbol and timeframe")
            previous = previous_by_type.get(swing.kind)
            kind: StructureKind | None = None
            if previous is not None:
                if swing.kind is SwingType.HIGH:
                    kind = StructureKind.HH if swing.price > previous.price else StructureKind.LH
                else:
                    kind = StructureKind.HL if swing.price > previous.price else StructureKind.LL
            events.append(StructureEvent(symbol, timeframe, swing, kind))
            previous_by_type[swing.kind] = swing
        return events
