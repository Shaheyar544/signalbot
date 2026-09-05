from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.events.models import Candle
from app.strategy.breakout import BreakoutEngine, BreakoutSetup, BreakoutStatus
from app.structure.csd import CSDDirection


@dataclass(frozen=True)
class RetestEvent:
    symbol: str
    timeframe: str
    candle: Candle
    breakout_level: Decimal
    status: BreakoutStatus
    setup: BreakoutSetup


class RetestEngine:
    def __init__(self, breakouts: BreakoutEngine) -> None:
        self.breakouts = breakouts

    def evaluate(self, candle: Candle) -> RetestEvent | None:
        if not candle.is_closed:
            return None
        setup = self.breakouts.get(candle.symbol, candle.timeframe)
        if setup is None or setup.status is not BreakoutStatus.PENDING_RETEST:
            return None
        setup = self.breakouts.advance(candle.symbol, candle.timeframe)
        if setup is None or setup.status is not BreakoutStatus.PENDING_RETEST:
            return None
        touches_zone = candle.low <= setup.zone_upper and candle.high >= setup.zone_lower
        valid_close = candle.close > setup.breakout_level if setup.direction is CSDDirection.BULLISH else candle.close < setup.breakout_level
        invalid_close = candle.close < setup.breakout_level if setup.direction is CSDDirection.BULLISH else candle.close > setup.breakout_level
        if invalid_close:
            resolved = self.breakouts.resolve(candle.symbol, candle.timeframe, BreakoutStatus.INVALIDATED)
            return RetestEvent(candle.symbol, candle.timeframe, candle, setup.breakout_level, BreakoutStatus.INVALIDATED, resolved or setup)
        if touches_zone and valid_close:
            resolved = self.breakouts.resolve(candle.symbol, candle.timeframe, BreakoutStatus.RETEST_DETECTED)
            return RetestEvent(candle.symbol, candle.timeframe, candle, setup.breakout_level, BreakoutStatus.RETEST_DETECTED, resolved or setup)
        return None
