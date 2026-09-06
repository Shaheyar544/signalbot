from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

class BacktestStatus(StrEnum):
    INCOMPLETE_COST_MODEL = "INCOMPLETE_COST_MODEL"
    INCOMPLETE_EXIT_MODEL = "INCOMPLETE_EXIT_MODEL"
    DIAGNOSTIC = "DIAGNOSTIC"
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"

@dataclass(frozen=True)
class BacktestRun:
    run_id: str; symbol: str; timeframe: str; status: BacktestStatus; warnings: tuple[str, ...]; created_at: datetime

@dataclass(frozen=True)
class TradeAudit:
    trade_id: str; run_id: str; signal_time: datetime; direction: str; entry_price: Decimal | None; stop_loss: Decimal | None; take_profit_1: Decimal | None; take_profit_2: Decimal | None; take_profit_3: Decimal | None; score_total: Decimal; score_classification: str; exit_time: datetime | None; exit_reason: str | None; gross_r: Decimal | None; costs_r: Decimal | None; net_r: Decimal | None; resolution_method: str | None; ambiguous_intrabar: bool
    bars_in_trade: int | None = None
    mfe_r: Decimal | None = None
    mae_r: Decimal | None = None
    symbol: str | None = None
    regime: str | None = None
    session: str | None = None
    # Added after the original audit schema: old persisted rows remain readable
    # but are intentionally INCOMPLETE_DATA for execution-sensitive research.
    entry_time: datetime | None = None
    exit_price: Decimal | None = None
    htf_agreement: dict[str, bool] | None = None
    confirmation_ema: bool | None = None
    confirmation_rsi: bool | None = None
    confirmation_macd: bool | None = None
    confirmation_volume: bool | None = None
    setup_csd: bool | None = None
    setup_breakout: bool | None = None
    setup_retest: bool | None = None
    entry_mode: str = "retest"

    @property
    def total_cost_r(self) -> Decimal | None:
        return self.costs_r
