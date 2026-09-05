"""Deterministic, analysis-only OHLC trade-resolution policy for replay."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from app.structure.csd import CSDDirection

class TradeOutcome(str, Enum): PENDING="PENDING"; SL="SL"; TP1="TP1"; TP2="TP2"; TP3="TP3"
class ResolutionMethod(str, Enum): PENDING="PENDING"; SL_ONLY="SL_ONLY"; TP_ONLY="TP_ONLY"; SAME_CANDLE_SL_FIRST="SAME_CANDLE"

@dataclass(frozen=True)
class TradePlan:
    direction: CSDDirection; entry: Decimal; stop_loss: Decimal; take_profits: tuple[Decimal, Decimal, Decimal]

@dataclass(frozen=True)
class TradeResolution:
    entered: bool; outcome: TradeOutcome; resolution_method: ResolutionMethod; ambiguous_intrabar: bool

class BacktestTradeResolver:
    """Official V1 policy: an OHLC candle reaching SL and TP resolves as SL."""
    def resolve(self, plan: TradePlan, *, low: Decimal, high: Decimal) -> TradeResolution:
        entered = low <= plan.entry <= high
        if not entered: return TradeResolution(False, TradeOutcome.PENDING, ResolutionMethod.PENDING, False)
        if plan.direction is CSDDirection.BULLISH:
            sl = low <= plan.stop_loss; hit = [high >= target for target in plan.take_profits]
        else:
            sl = high >= plan.stop_loss; hit = [low <= target for target in plan.take_profits]
        if sl and any(hit): return TradeResolution(True, TradeOutcome.SL, ResolutionMethod.SAME_CANDLE_SL_FIRST, True)
        if sl: return TradeResolution(True, TradeOutcome.SL, ResolutionMethod.SL_ONLY, False)
        for outcome, reached in zip((TradeOutcome.TP3, TradeOutcome.TP2, TradeOutcome.TP1), reversed(hit)):
            if reached: return TradeResolution(True, outcome, ResolutionMethod.TP_ONLY, False)
        return TradeResolution(True, TradeOutcome.PENDING, ResolutionMethod.PENDING, False)
