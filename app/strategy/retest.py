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
    quality: Decimal = Decimal("0")


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
            span = candle.high - candle.low
            # Close position in the rejection candle expresses how cleanly price reclaimed the level.
            quality = ((candle.close - candle.low) / span if setup.direction is CSDDirection.BULLISH
                       else (candle.high - candle.close) / span) if span > 0 else Decimal(0)
            return RetestEvent(candle.symbol, candle.timeframe, candle, setup.breakout_level,
                               BreakoutStatus.RETEST_DETECTED, resolved or setup, min(max(quality, Decimal(0)), Decimal(1)))
        return None
