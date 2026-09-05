# Multi-Pair CSD Signal Engine

Signal-only cryptocurrency market analysis for independently monitored Binance USD-M Futures pairs. Its domain language keeps market-data facts separate from derived structure and future signals.

## Market data

**Candle**:
An OHLCV observation for one symbol and timeframe, identified by its opening time.
_Avoid_: Bar, price tick

**Closed candle**:
A candle whose exchange interval has ended and whose OHLCV values are final for strategy evaluation.
_Avoid_: Forming candle, live candle

**Primary timeframe**:
The configured timeframe on which CSD is evaluated; Phase 2 uses the configured 15m primary timeframe.
_Avoid_: Confirmation timeframe

**Confirmation timeframe**:
A configured higher timeframe that supplies context but does not itself create a CSD event.
_Avoid_: Primary timeframe

## Structure

**Swing point**:
A confirmed local high or low whose surrounding configured candles establish it as a pivot.
_Avoid_: Any candle high, any candle low

**Market structure**:
The ordered sequence of confirmed swing points, classified as higher high, higher low, lower high, or lower low.
_Avoid_: Trend, price action

**CSD event**:
A candidate change-of-structure event created only when a closed primary-timeframe candle validly closes beyond a meaningful opposing swing level.
_Avoid_: Wick break, intrabar break, trade signal

**Wick-only break**:
A candle whose high/low crosses a swing level but whose close returns to the pre-break side; it is not a CSD event.
_Avoid_: Confirmed break

## Setup lifecycle

**Breakout**:
A CSD event accepted as the level that price must subsequently retest; it is not an entry or trade instruction.
_Avoid_: Trade entry, confirmed signal

**Retest zone**:
The configurable price range around a breakout level in which a retest may occur.
_Avoid_: Exact retest price

**Retest**:
A closed candle that returns to a retest zone and closes back on the valid side of the breakout level.
_Avoid_: Touch, wick-only return

**Invalidation**:
The terminal outcome for a breakout setup when a closed candle confirms failure on the wrong side of its breakout level.
_Avoid_: Retest, new CSD

**Expired setup**:
A pending breakout setup whose configured retest window elapsed without a valid retest.
_Avoid_: Invalidation, retest

## Confirmation

**Confirmation result**:
An evidence record describing which configured supporting conditions hold for a completed breakout/retest setup.
_Avoid_: Trade signal, order

**Confidence score**:
The configured 0–10 total assigned to required setup conditions and supporting confirmation conditions.
_Avoid_: Probability, guarantee

**Signal classification**:
The confidence-score label `NO_TRADE`, `WATCH`, `GOOD_SIGNAL`, or `STRONG_SIGNAL`.
_Avoid_: Trade instruction

## Risk analysis

**Entry zone**:
The dynamic price interval derived from a validated retest; it is a reference range, not an executed order.
_Avoid_: Filled entry, market order

**Stop loss**:
The structure-based invalidation price below a bullish retest or above a bearish retest.
_Avoid_: Guaranteed loss limit

**Risk unit (R)**:
The absolute distance between reference entry and stop loss.
_Avoid_: Return, profit

**Take-profit level**:
A reference price derived from a configured multiple of R; it is not an order.
_Avoid_: Executed target

**Structure target (TP4)**:
The nearest confirmed opposing swing beyond the reference entry, used as an optional fourth informational take-profit level.
_Avoid_: Guaranteed target, arbitrary multiple of R

## Signal records

**Signal record**:
The persisted analysis snapshot for a scored, risk-calculated setup. It is not a trade or an instruction to trade.
_Avoid_: Position, order

**Stable signal ID**:
The deterministic identity of one setup, derived from its symbol, timeframe, direction, and breakout structure reference.
_Avoid_: Random identifier, exchange order ID

**Duplicate signal**:
An attempt to persist the same stable signal ID more than once within its lifecycle.
_Avoid_: Follow-up lifecycle record

**Historical replay**:
Chronological delivery of stored closed candles through the same strategy engine used for live data.
_Avoid_: Backtest-specific strategy

**Official V1 intrabar replay policy**:
If one historical candle reaches both the applicable stop loss and any take-profit level, record `SL` with resolution method `SAME_CANDLE_SL_FIRST` and `ambiguous_intrabar: true`. Include it in every official performance metric.
_Avoid_: Target-first inference, excluding ambiguous trades, optimistic intrabar assumptions

## Notifications

**Notification provider**:
An isolated adapter that attempts delivery of a signal record through one configured external channel.
_Avoid_: Trading provider, exchange adapter

**Notification dispatch**:
The independent delivery attempt to every enabled provider for one persisted signal record.
_Avoid_: Single point of failure

**Delivery result**:
The recorded success or failure of one provider attempt; a failure does not change the signal record or block other providers.
_Avoid_: Signal outcome

## Operations

**Health snapshot**:
The local read-only status of process, database, WebSocket, and last-candle state.
_Avoid_: Trading status

**Persistent data volume**:
The deployment-managed filesystem location that retains the SQLite database across container restarts.
_Avoid_: Container filesystem
