from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from app.structure.csd import CSDEvent, CSDDirection


class BreakoutStatus(StrEnum):
    PENDING_RETEST = "PENDING_RETEST"
    RETEST_DETECTED = "RETEST_DETECTED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class BreakoutSetup:
    symbol: str
    timeframe: str
    direction: CSDDirection
    breakout_level: Decimal
    zone_lower: Decimal
    zone_upper: Decimal
    source_csd: CSDEvent
    status: BreakoutStatus = BreakoutStatus.PENDING_RETEST
    bars_after_breakout: int = 0


class BreakoutEngine:
    """Owns independent pending retest setups keyed by pair and timeframe."""
    def __init__(self, retest_zone_percent: Decimal = Decimal("0.20"), maximum_bars_after_breakout: int = 12) -> None:
        if retest_zone_percent < 0 or maximum_bars_after_breakout < 0:
            raise ValueError("retest configuration cannot be negative")
        self.retest_zone_percent = retest_zone_percent
        self.maximum_bars_after_breakout = maximum_bars_after_breakout
        self._setups: dict[tuple[str, str], BreakoutSetup] = {}

    def start(self, event: CSDEvent) -> BreakoutSetup:
        level = event.broken_swing.price
        offset = level * self.retest_zone_percent / Decimal(100)
        setup = BreakoutSetup(event.symbol, event.timeframe, event.direction, level, level - offset, level + offset, event)
        self._setups[(event.symbol, event.timeframe)] = setup
        return setup

    def get(self, symbol: str, timeframe: str) -> BreakoutSetup | None:
        return self._setups.get((symbol, timeframe))

    def resolve(self, symbol: str, timeframe: str, status: BreakoutStatus) -> BreakoutSetup | None:
        current = self._setups.get((symbol, timeframe))
        if current is None:
            return None
        resolved = replace(current, status=status)
        self._setups[(symbol, timeframe)] = resolved
        return resolved

    def advance(self, symbol: str, timeframe: str) -> BreakoutSetup | None:
        current = self._setups.get((symbol, timeframe))
        if current is None or current.status is not BreakoutStatus.PENDING_RETEST:
            return current
        advanced = replace(current, bars_after_breakout=current.bars_after_breakout + 1)
        if advanced.bars_after_breakout > self.maximum_bars_after_breakout:
            advanced = replace(advanced, status=BreakoutStatus.EXPIRED)
        self._setups[(symbol, timeframe)] = advanced
        return advanced
