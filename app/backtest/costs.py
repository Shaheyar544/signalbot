from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.config.settings import CostSettings
from app.structure.csd import CSDDirection


@dataclass(frozen=True)
class CostBreakdown:
    entry_fee_r: Decimal
    exit_fee_r: Decimal
    entry_slippage_r: Decimal
    exit_slippage_r: Decimal
    funding_r: Decimal
    total_r: Decimal


class CostModel:
    def __init__(self, settings: CostSettings) -> None:
        self.settings = settings

    def entry_cost_percent(self) -> Decimal:
        fee = self.settings.taker_fee_percent if self.settings.entry_order_type == "taker" else self.settings.maker_fee_percent
        return fee + self.settings.slippage_percent

    def exit_cost_percent(self, *, is_stop: bool) -> Decimal:
        fee = self.settings.taker_fee_percent if self.settings.exit_order_type == "taker" else self.settings.maker_fee_percent
        slippage = self.settings.slippage_percent_stop if is_stop else self.settings.slippage_percent
        return fee + slippage

    def funding_r(self, *, opened_at: datetime, closed_at: datetime, risk_unit_percent: Decimal) -> Decimal:
        if closed_at <= opened_at or risk_unit_percent <= 0 or self.settings.funding_rate_source == "none":
            return Decimal(0)
        if self.settings.funding_rate_source == "historical":
            raise ValueError("historical funding source is not configured for V2")
        boundaries = int((closed_at - opened_at) / timedelta(hours=8))
        # TODO: replace with historical funding rate lookup per symbol.
        return Decimal(boundaries) * self.settings.funding_rate_fixed_percent / risk_unit_percent

    def breakdown(self, *, direction: CSDDirection, entry: Decimal, stop_loss: Decimal,
                  exit_price: Decimal, is_stop_exit: bool, opened_at: datetime,
                  closed_at: datetime) -> CostBreakdown:
        del direction, exit_price  # Costs are side-independent percent-of-notional assumptions.
        risk_unit_percent = abs(entry - stop_loss) / entry * Decimal(100)
        if risk_unit_percent <= 0:
            raise ValueError("entry and stop_loss must define positive risk")
        entry_fee_percent = self.settings.taker_fee_percent if self.settings.entry_order_type == "taker" else self.settings.maker_fee_percent
        exit_fee_percent = self.settings.taker_fee_percent if self.settings.exit_order_type == "taker" else self.settings.maker_fee_percent
        entry_slippage_percent = self.settings.slippage_percent
        exit_slippage_percent = self.settings.slippage_percent_stop if is_stop_exit else self.settings.slippage_percent
        entry_fee_r = entry_fee_percent / risk_unit_percent
        exit_fee_r = exit_fee_percent / risk_unit_percent
        entry_slippage_r = entry_slippage_percent / risk_unit_percent
        exit_slippage_r = exit_slippage_percent / risk_unit_percent
        funding = self.funding_r(opened_at=opened_at, closed_at=closed_at, risk_unit_percent=risk_unit_percent)
        total = entry_fee_r + exit_fee_r + entry_slippage_r + exit_slippage_r + funding
        return CostBreakdown(entry_fee_r, exit_fee_r, entry_slippage_r, exit_slippage_r, funding, total)
