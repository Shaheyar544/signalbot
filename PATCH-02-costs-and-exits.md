# Patch 02 — Cost model + real exit policy engine

Target repo: `signalbot`, state as of commit `8add4f3` (PATCH-01 complete —
graded scoring, gated swings, `has_csd`/`has_breakout`/`has_retest`
hard-coding removed, 72/72 tests passing, verified).

Scope: `app/backtest/` (new package), `app/backtests.py`, `app/backtest_runner.py`,
`app/backtesting.py`, `app/config/settings.py`, `config.yaml`,
`app/storage/repositories.py`. Do not touch scoring, swing gating, live
WebSocket path, or notifications in this patch.

## Why this patch exists

`app/backtest_runner.py` currently resolves every trade using
`BacktestTradeResolver().resolve(plan, low=current.low, high=current.high)`
where `current` is **the same candle that generated the signal** — the candle
where retest was detected and risk was calculated. That candle closed before
the entry could have happened. Every `gross_r`/`net_r` this runner has ever
produced is evaluated against the wrong bar. The `BacktestStatus` enum already
carries `INCOMPLETE_EXIT_MODEL` and `INCOMPLETE_COST_MODEL` — the code has been
honest that this isn't done. This patch does it.

No backtest number produced before this patch is valid. Do not carry any prior
"win rate" or "R achieved" figures forward.

---

## Part C — Cost model

### C1. Settings

In `app/config/settings.py`, add, following the existing `RiskSettings`
pattern exactly:

```python
@dataclass(frozen=True)
class CostSettings:
    taker_fee_percent: Decimal = Decimal("0.05")       # per side
    maker_fee_percent: Decimal = Decimal("0.02")       # per side
    entry_order_type: str = "taker"                     # "taker" | "maker"
    exit_order_type: str = "taker"
    slippage_percent: Decimal = Decimal("0.02")         # per side, normal exits
    slippage_percent_stop: Decimal = Decimal("0.05")    # per side, stop exits
    funding_rate_fixed_percent: Decimal = Decimal("0.01")  # per 8h, until historical funding is wired in
```

Wire it into `Settings` and `load_settings()` exactly like `risk` is wired in
today (new `cost = raw.get("cost", {})` block, validate all values `>= 0`,
validate `entry_order_type`/`exit_order_type` are one of `{"taker", "maker"}`).
Add a matching `cost:` section to `config.yaml` with the same defaults.

Note on funding: real historical funding-rate data isn't wired up yet. Use
`funding_rate_fixed_percent` charged per 8-hour boundary crossed while a
position is open, applied to the full position notional at each boundary. Add
a `# TODO: replace with historical funding rate lookup per symbol` comment.
Do not silently skip funding — a fixed approximation that's flagged as
approximate is better than pretending it's zero.

### C2. `app/backtest/costs.py`

New package `app/backtest/__init__.py` (empty) and `app/backtest/costs.py`:

```python
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
        fee = (self.settings.taker_fee_percent if self.settings.entry_order_type == "taker"
               else self.settings.maker_fee_percent)
        return fee + self.settings.slippage_percent

    def exit_cost_percent(self, *, is_stop: bool) -> Decimal:
        fee = (self.settings.taker_fee_percent if self.settings.exit_order_type == "taker"
               else self.settings.maker_fee_percent)
        slippage = self.settings.slippage_percent_stop if is_stop else self.settings.slippage_percent
        return fee + slippage

    def funding_r(self, *, opened_at: datetime, closed_at: datetime, risk_unit_percent: Decimal) -> Decimal:
        """Number of 8h boundaries crossed, charged against the position, expressed in R.
        risk_unit_percent = abs(entry - stop) / entry * 100, used to convert a
        percent-of-notional funding charge into R terms."""
        if closed_at <= opened_at or risk_unit_percent <= 0:
            return Decimal(0)
        boundaries = int((closed_at - opened_at) / timedelta(hours=8))
        funding_percent = boundaries * self.settings.funding_rate_fixed_percent
        return funding_percent / risk_unit_percent

    def breakdown(self, *, direction: CSDDirection, entry: Decimal, stop_loss: Decimal,
                  exit_price: Decimal, is_stop_exit: bool, opened_at: datetime,
                  closed_at: datetime) -> CostBreakdown:
        risk_unit_percent = abs(entry - stop_loss) / entry * Decimal(100)
        entry_fee_r = self.entry_cost_percent() / risk_unit_percent
        exit_pct = self.exit_cost_percent(is_stop=is_stop_exit)
        # Split fee/slippage components out of exit_pct proportionally for reporting;
        # keep it simple: report combined exit cost as exit_fee_r, slippage folded in
        # separately for transparency using the same percentages.
        exit_fee_r = exit_pct / risk_unit_percent
        entry_slippage_r = Decimal(0)  # already folded into entry_fee_r above; kept as an explicit field for audit clarity
        exit_slippage_r = Decimal(0)   # already folded into exit_fee_r above
        funding = self.funding_r(opened_at=opened_at, closed_at=closed_at, risk_unit_percent=risk_unit_percent)
        total = entry_fee_r + exit_fee_r + funding
        return CostBreakdown(entry_fee_r, exit_fee_r, entry_slippage_r, exit_slippage_r, funding, total)
```

Implementer's note: the fee/slippage split above is deliberately simplified —
report the *combined* per-side cost in `entry_fee_r`/`exit_fee_r` rather than
inventing a false precision split. If you have a cleaner way to keep fee and
slippage as genuinely separate fields without adding complexity, do that
instead, but don't lose the "total_r must equal the true combined cost"
property.

### C3. Required tests

`tests/test_costs.py`: assert `entry_cost_percent()` sums fee+slippage
correctly for both maker/taker; assert `exit_cost_percent(is_stop=True)` uses
the wider stop slippage; assert `funding_r` returns `0` for a trade held under
8 hours and a nonzero value for one held 24 hours (3 boundaries); assert
`breakdown().total_r` matches the sum of its own components exactly (no
silent double-counting or dropped terms).

---

## Part D — Exit policy engine (replaces the same-candle resolver)

### D1. Settings

In `app/config/settings.py`, add:

```python
@dataclass(frozen=True)
class ExitLeg:
    target_r: Decimal
    size_percent: Decimal


@dataclass(frozen=True)
class ExitPolicySettings:
    name: str = "scaled"                          # "single_target" | "scaled"
    legs: tuple[ExitLeg, ...] = (
        ExitLeg(Decimal("1.0"), Decimal("50")),
        ExitLeg(Decimal("2.0"), Decimal("25")),
        ExitLeg(Decimal("3.0"), Decimal("25")),
    )
    move_stop_to_breakeven_after_leg: int | None = 1
    breakeven_offset_r: Decimal = Decimal("0.1")
    time_stop_bars: int | None = 48
```

Validate in `load_settings()`: leg `size_percent` values sum to exactly `100`;
`move_stop_to_breakeven_after_leg` if set is a valid 1-indexed leg number;
`time_stop_bars` if set is positive. Add a matching `exit_policy:` section to
`config.yaml`.

### D2. `app/backtest/exits.py` — the trade lifecycle simulator

This is the core of the patch. Replace same-candle resolution with a real
walk-forward simulator that consumes candles one at a time, exactly the way
the live strategy engine does — no scanning ahead into a full array.

```python
from __future__ import annotations

from dataclasses import dataclass, field
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
    bars_since_entry: int = 0
    bars_since_signal: int = 0
    exit_reason: str | None = None          # "SL" | "TP<i>_LAST_LEG" | "TIME_STOP" | "END_OF_DATA"
    ambiguous_intrabar_events: int = 0
    remaining_size_percent: Decimal = Decimal("100")


class ExitPolicyEngine:
    """Advances one SimulatedTrade forward one candle at a time.
    Never receives more than the current candle — same seam discipline as the
    live strategy engine and CandleStore.get_recent_as_of."""

    def __init__(self, settings: ExitPolicySettings) -> None:
        self.settings = settings

    def open_trade(self, *, direction: CSDDirection, entry_low: Decimal, entry_high: Decimal,
                    reference_entry: Decimal, stop_loss: Decimal) -> SimulatedTrade:
        legs = [LegFill(leg.target_r, leg.size_percent) for leg in self.settings.legs]
        return SimulatedTrade(direction, entry_low, entry_high, reference_entry, stop_loss,
                              legs, current_stop=stop_loss)

    def advance(self, trade: SimulatedTrade, candle: Candle) -> SimulatedTrade:
        """Mutates and returns trade. Call once per closed candle, in order,
        starting with the candle AFTER the signal candle."""
        if trade.state in (TradeState.CLOSED, TradeState.EXPIRED_UNFILLED):
            return trade
        trade.bars_since_signal += 1

        if trade.state is TradeState.AWAITING_ENTRY:
            entered = candle.low <= trade.entry_high and candle.high >= trade.entry_low
            if not entered:
                if (self.settings.time_stop_bars is not None
                        and trade.bars_since_signal > self.settings.time_stop_bars):
                    trade.state = TradeState.EXPIRED_UNFILLED
                return trade
            trade.entry_fill_price = trade.reference_entry
            trade.state = TradeState.OPEN

        trade.bars_since_entry += 1
        risk_unit = abs(trade.entry_fill_price - trade.initial_stop_loss)

        # Pessimistic same-candle rule: if this candle's range contains both
        # the current stop and any unfilled leg's target, assume the stop
        # filled first. This must hold even mid-trade after partial fills.
        stop_hit = (candle.low <= trade.current_stop if trade.direction is CSDDirection.BULLISH
                    else candle.high >= trade.current_stop)
        unfilled_legs_hit = [
            leg for leg in trade.legs if not leg.filled and self._target_hit(trade, leg, candle)
        ]

        if stop_hit and unfilled_legs_hit:
            trade.ambiguous_intrabar_events += 1
            self._close_at_stop(trade)
            return trade
        if stop_hit:
            self._close_at_stop(trade)
            return trade

        for leg in sorted(unfilled_legs_hit, key=lambda l: l.target_r):
            leg.filled = True
            leg.filled_at_candle_index = trade.bars_since_entry
            trade.remaining_size_percent -= leg.size_percent
            leg_index = trade.legs.index(leg) + 1
            if (self.settings.move_stop_to_breakeven_after_leg is not None
                    and leg_index >= self.settings.move_stop_to_breakeven_after_leg):
                offset = risk_unit * self.settings.breakeven_offset_r
                trade.current_stop = (trade.entry_fill_price + offset if trade.direction is CSDDirection.BULLISH
                                       else trade.entry_fill_price - offset)

        if all(leg.filled for leg in trade.legs):
            trade.state = TradeState.CLOSED
            trade.exit_reason = f"TP{len(trade.legs)}_LAST_LEG"
            return trade

        if (self.settings.time_stop_bars is not None
                and trade.bars_since_entry >= self.settings.time_stop_bars):
            trade.state = TradeState.CLOSED
            trade.exit_reason = "TIME_STOP"

        return trade

    def close_at_end_of_data(self, trade: SimulatedTrade, last_candle: Candle) -> SimulatedTrade:
        """Call if candles run out while a trade is still OPEN. Marks it closed
        at the last close price so it isn't silently dropped from results."""
        if trade.state is TradeState.OPEN:
            trade.state = TradeState.CLOSED
            trade.exit_reason = "END_OF_DATA"
        return trade

    @staticmethod
    def _target_hit(trade: SimulatedTrade, leg: LegFill, candle: Candle) -> bool:
        risk_unit = abs(trade.entry_fill_price - trade.initial_stop_loss)
        if trade.direction is CSDDirection.BULLISH:
            target_price = trade.entry_fill_price + risk_unit * leg.target_r
            return candle.high >= target_price
        target_price = trade.entry_fill_price - risk_unit * leg.target_r
        return candle.low <= target_price

    @staticmethod
    def _close_at_stop(trade: SimulatedTrade) -> None:
        trade.state = TradeState.CLOSED
        trade.exit_reason = "SL"
```

Then a separate pure function to turn a fully-resolved `SimulatedTrade` into
gross R, using each leg's actual `target_r` weighted by `size_percent`, plus
the stop-loss portion for whatever `remaining_size_percent` was open when the
stop hit:

```python
def gross_r(trade: SimulatedTrade) -> Decimal:
    if trade.state is not TradeState.CLOSED or trade.exit_fill_price_r is None:
        raise ValueError("gross_r requires a closed trade")
    # Implementer: sum (leg.target_r * leg.size_percent/100) for filled legs,
    # plus (stop_r_at_exit * remaining_size_percent/100) if stop-closed,
    # plus 0 for time-stop/end-of-data (or the actual candle-close R at that
    # point — pick one and document it; recommend using actual close price R
    # for TIME_STOP/END_OF_DATA rather than 0, since a position was live and
    # had a real P&L when forcibly closed).
    ...
```

Fill in `gross_r` fully — the stub above intentionally leaves the exact
weighted-sum implementation to you since it depends on exactly which fields
you end up tracking on `SimulatedTrade` (you may need to add a
`stop_price_at_exit` or `time_stop_close_price` field; add whatever's needed).
Do not leave it partially implemented — a trade that's closed but has no
computable R is worse than not running the backtest at all, because it will
silently disappear from aggregate stats instead of counting as a loss/win.

### D3. Rewrite `backtest_runner.py`

The current model calls `capture()` synchronously at signal time with only the
signal candle in scope. That has to change to a **two-phase** design:

1. **Phase 1 (existing):** feed candles through `CSDStrategyEngine` exactly as
   today. When `on_risk_analysis` fires, don't resolve anything — instead
   register a `SimulatedTrade` via `ExitPolicyEngine.open_trade(...)` in a
   list of "trades awaiting resolution," keyed by `(symbol, timeframe)`, along
   with the candle index at which it was opened.
2. **Phase 2 (new):** after all candles have been fed through the strategy
   once (so all signals are known), replay the same candle sequence a second
   time — this is fine, this is backtest code, not the live path — and for
   each candle, call `ExitPolicyEngine.advance(trade, candle)` for every
   still-open trade for that symbol/timeframe, starting from the candle
   *after* that trade's signal candle. Never call `advance()` with a candle at
   or before the signal candle. Never let a trade see candles from a different
   symbol/timeframe.

   Alternative (preferred if it's not much harder): do it in one pass by
   maintaining live `SimulatedTrade` objects per key and calling `advance()`
   inline as each new candle for that key arrives, immediately after the
   existing strategy call for that candle. This avoids the second pass
   entirely and stays closer to the live/replay parity goal. Prefer this if
   feasible; fall back to two-phase only if it meaningfully complicates the
   code.

Once a trade reaches `CLOSED` or `EXPIRED_UNFILLED`, compute:

```python
cost_model = CostModel(self.settings.cost)
breakdown = cost_model.breakdown(
    direction=trade.direction, entry=trade.entry_fill_price, stop_loss=trade.initial_stop_loss,
    exit_price=..., is_stop_exit=(trade.exit_reason == "SL"),
    opened_at=..., closed_at=...,
)
gross = gross_r(trade)
net = gross - breakdown.total_r
```

and persist via `TradeAudit` with `gross_r`, `costs_r=breakdown.total_r`,
`net_r=net` populated (currently always `None`). Update `BacktestStatus`: once
this patch is complete and tested, the run status should no longer be
`INCOMPLETE_EXIT_MODEL` — introduce a new status, e.g. `DIAGNOSTIC` (already
in the enum) or add `EXIT_AND_COST_MODEL_COMPLETE`, and update the warnings
tuple accordingly. Do not claim `COMPLETE` outright — walk-forward validation,
the random baseline, and multi-symbol testing haven't happened yet; that's the
next patch.

Delete `BacktestTradeResolver`/`TradePlan` from `app/backtesting.py` once
nothing references the same-candle resolution path, or explicitly repurpose
it as an internal helper used only inside `ExitPolicyEngine._target_hit`/
`_close_at_stop` if the SL-first-on-ambiguity logic is worth reusing verbatim
— check whether it's cleaner to keep it as a single-candle helper called by
the new per-candle `advance()` loop rather than duplicating that logic. Your
call; just don't leave two independent implementations of "which fires first
in an ambiguous candle" that could silently disagree.

### D4. Required tests

`tests/test_exit_policy.py`, covering at minimum:

- **Entry never fills within the signal candle** — `advance()` is never called
  with the signal candle itself; write a test asserting a trade opened on
  candle N and only entering on candle N+1's range doesn't fill early even if
  candle N's range also touched the entry zone.
- **Scaled exits fill legs independently** — a candle sequence that hits TP1
  then later TP2 then later TP3, asserting `remaining_size_percent` decreases
  correctly and each leg's `filled_at_candle_index` is distinct.
- **Breakeven stop movement** — after leg 1 fills, `current_stop` moves to
  `entry + breakeven_offset_r * risk_unit` (or minus, for shorts), and a
  subsequent candle that would have hit the *original* stop but not the new
  one does not close the trade.
- **Same-candle SL-and-target ambiguity resolves to SL** — a single candle
  whose range contains both the current stop and an unfilled leg's target
  must close as `SL`, and `ambiguous_intrabar_events` increments.
- **Time stop force-closes** — a trade with no SL/TP hit for
  `time_stop_bars` candles closes with `exit_reason == "TIME_STOP"` and a
  computable (non-`None`) `gross_r`.
- **End of data force-closes** — same, but via `close_at_end_of_data`.
- **Unfilled entries expire, not hang forever** — a trade whose entry zone is
  never touched within `time_stop_bars` of the signal reaches
  `EXPIRED_UNFILLED` and is excluded from R-based stats (it's not a loss or a
  win — it never happened).

`tests/test_costs.py` from Part C.

Update `tests/test_backtest_runner.py`: it currently likely asserts against
the old same-candle resolution behavior (check it — if it constructs a
single-candle scenario and expects an immediate `TP1`/`SL` result, that
assertion is now testing the bug you're removing). Rewrite it to construct a
multi-candle sequence: signal candle, then N candles of price action that
plays out a full trade lifecycle, then assert the persisted `TradeAudit` has
correct non-`None` `gross_r`/`costs_r`/`net_r`.

---

## Acceptance for this patch

- `gross_r`, `costs_r`, `net_r` are populated (non-`None`) for every resolved
  trade in `backtest_runner.py` output — check by running the runner against
  a real multi-week candle fixture and inspecting `backtest_trades` rows
  directly, not just checking tests pass.
- No trade is ever resolved using the signal candle's own OHLC.
- Full test suite passes, including new `test_exit_policy.py` and
  `test_costs.py`, and the rewritten `test_backtest_runner.py`.
- `grep -rn "BacktestTradeResolver" app/` — confirm every remaining reference
  is either deleted or explicitly repurposed inside the new exit engine, not
  left as dead code alongside a duplicate implementation.
- Report the actual net-of-cost break-even win rate implied by your default
  `exit_policy` + `cost` config for a 1R/2R/3R scaled exit (this is arithmetic,
  not a backtest run) — sanity-check it against roughly 55–65% and flag if
  your defaults land far outside that range.
- Do not start walk-forward, the random baseline, or multi-symbol testing in
  this patch — stop here for review.
