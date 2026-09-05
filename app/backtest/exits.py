from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.config.settings import ExitPolicySettings
from app.events.models import Candle
from app.structure.csd import CSDDirection


class TradeState(StrEnum):
    AWAITING_ENTRY = "AWAITING_ENTRY"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXPIRED_UNFILLED = "EXPIRED_UNFILLED"


@dataclass
class LegFill:
    target_r: Decimal
    size_percent: Decimal
    filled: bool = False
    filled_at_candle_index: int | None = None


@dataclass
class SimulatedTrade:
    direction: CSDDirection
    entry_low: Decimal
    entry_high: Decimal
    reference_entry: Decimal
    initial_stop_loss: Decimal
    legs: list[LegFill]
    state: TradeState = TradeState.AWAITING_ENTRY
    current_stop: Decimal | None = None
    entry_fill_price: Decimal | None = None
    entered_at: datetime | None = None
    closed_at: datetime | None = None
    exit_price: Decimal | None = None
    bars_since_entry: int = 0
    bars_since_signal: int = 0
    exit_reason: str | None = None
    resolution_method: str | None = None
    ambiguous_intrabar_events: int = 0
    remaining_size_percent: Decimal = Decimal("100")


class ExitPolicyEngine:
    """Sequential exit simulator; callers supply only the current closed candle."""
    def __init__(self, settings: ExitPolicySettings) -> None:
        self.settings = settings

    def open_trade(self, *, direction: CSDDirection, entry_low: Decimal, entry_high: Decimal,
                   reference_entry: Decimal, stop_loss: Decimal) -> SimulatedTrade:
        return SimulatedTrade(direction, entry_low, entry_high, reference_entry, stop_loss,
                              [LegFill(leg.target_r, leg.size_percent) for leg in self.settings.legs],
                              current_stop=stop_loss)

    def advance(self, trade: SimulatedTrade, candle: Candle) -> SimulatedTrade:
        if trade.state in {TradeState.CLOSED, TradeState.EXPIRED_UNFILLED}:
            return trade
        trade.bars_since_signal += 1
        if trade.state is TradeState.AWAITING_ENTRY:
            if not (candle.low <= trade.entry_high and candle.high >= trade.entry_low):
                if self.settings.time_stop_bars is not None and trade.bars_since_signal > self.settings.time_stop_bars:
                    trade.state = TradeState.EXPIRED_UNFILLED
                return trade
            trade.entry_fill_price = trade.reference_entry
            trade.entered_at = candle.close_time
            trade.state = TradeState.OPEN

        trade.bars_since_entry += 1
        stop_hit = candle.low <= trade.current_stop if trade.direction is CSDDirection.BULLISH else candle.high >= trade.current_stop
        targets_hit = [leg for leg in trade.legs if not leg.filled and self._target_hit(trade, leg, candle)]
        if stop_hit and targets_hit:
            trade.ambiguous_intrabar_events += 1
            self._close_at_stop(trade, candle, "SAME_CANDLE")
            return trade
        if stop_hit:
            self._close_at_stop(trade, candle, "SL_ONLY")
            return trade

        for leg in sorted(targets_hit, key=lambda item: item.target_r):
            leg.filled = True
            leg.filled_at_candle_index = trade.bars_since_entry
            trade.remaining_size_percent -= leg.size_percent
            leg_index = trade.legs.index(leg) + 1
            if self.settings.move_stop_to_breakeven_after_leg is not None and leg_index >= self.settings.move_stop_to_breakeven_after_leg:
                risk = abs(trade.entry_fill_price - trade.initial_stop_loss)
                offset = risk * self.settings.breakeven_offset_r
                trade.current_stop = trade.entry_fill_price + offset if trade.direction is CSDDirection.BULLISH else trade.entry_fill_price - offset
        if all(leg.filled for leg in trade.legs):
            trade.state = TradeState.CLOSED
            trade.exit_reason = f"TP{len(trade.legs)}_LAST_LEG"
            trade.resolution_method = "TP_ONLY"
            trade.exit_price = self._target_price(trade, trade.legs[-1])
            trade.closed_at = candle.close_time
            return trade
        if self.settings.time_stop_bars is not None and trade.bars_since_entry >= self.settings.time_stop_bars:
            trade.state = TradeState.CLOSED
            trade.exit_reason = "TIME_STOP"
            trade.resolution_method = "TIME_STOP"
            trade.exit_price = candle.close
            trade.closed_at = candle.close_time
        return trade

    def close_at_end_of_data(self, trade: SimulatedTrade, last_candle: Candle) -> SimulatedTrade:
        if trade.state is TradeState.OPEN:
            trade.state = TradeState.CLOSED
            trade.exit_reason = "END_OF_DATA"
            trade.resolution_method = "END_OF_DATA"
            trade.exit_price = last_candle.close
            trade.closed_at = last_candle.close_time
        return trade

    @staticmethod
    def _target_price(trade: SimulatedTrade, leg: LegFill) -> Decimal:
        risk = abs(trade.entry_fill_price - trade.initial_stop_loss)
        return trade.entry_fill_price + risk * leg.target_r if trade.direction is CSDDirection.BULLISH else trade.entry_fill_price - risk * leg.target_r

    def _target_hit(self, trade: SimulatedTrade, leg: LegFill, candle: Candle) -> bool:
        target = self._target_price(trade, leg)
        return candle.high >= target if trade.direction is CSDDirection.BULLISH else candle.low <= target

    @staticmethod
    def _close_at_stop(trade: SimulatedTrade, candle: Candle, method: str) -> None:
        trade.state = TradeState.CLOSED
        trade.exit_reason = "SL"
        trade.resolution_method = method
        trade.exit_price = trade.current_stop
        trade.closed_at = candle.close_time


def gross_r(trade: SimulatedTrade) -> Decimal:
    if trade.state is not TradeState.CLOSED or trade.entry_fill_price is None or trade.exit_price is None:
        raise ValueError("gross_r requires a closed, filled trade")
    filled_r = sum((leg.target_r * leg.size_percent / Decimal(100) for leg in trade.legs if leg.filled), Decimal(0))
    if trade.remaining_size_percent == 0:
        return filled_r
    risk = abs(trade.entry_fill_price - trade.initial_stop_loss)
    if risk == 0:
        raise ValueError("gross_r requires positive risk")
    close_r = ((trade.exit_price - trade.entry_fill_price) / risk if trade.direction is CSDDirection.BULLISH
               else (trade.entry_fill_price - trade.exit_price) / risk)
    return filled_r + close_r * trade.remaining_size_percent / Decimal(100)
