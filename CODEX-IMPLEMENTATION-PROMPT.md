# Codex Implementation Prompt --- ETH CSD Signal Bot V1

Act as a senior Python backend engineer, quantitative developer and
production systems engineer.

Read `ETH-CSD-SIGNAL-BOT-SPEC.md` and implement it in the current
repository.

## Rules

-   V1 is **signal-only**.
-   Never place Binance orders.
-   Never request trading/withdrawal API permissions.
-   Never hard-code today's ETH levels.
-   Use dynamic swings and structure.
-   Confirm normal signals using closed 15M candles.
-   Keep strategy independent from notification providers.
-   Never log secrets.
-   Never allow a notification failure to crash the strategy.
-   Live mode and replay mode must use the same strategy engine.

## Phase 1 --- Inspect first

Before editing: 1. Inspect repository structure. 2. Identify Python
version. 3. Inspect existing dependencies/config/database/Docker. 4.
Reuse suitable existing infrastructure. 5. Avoid unrelated rewrites. 6.
State a concise implementation plan.

## Phase 2 --- Implement domain models

Create typed models for: - Candle - SwingPoint - StructureEvent -
CSDEvent - BreakoutEvent - RetestEvent - ConfirmationResult - Signal -
SignalEvent - NotificationResult

## Phase 3 --- Market data

Implement Binance USD-M Futures: - ETHUSDT - 15M - 1H - 4H - REST
bootstrap - WebSocket updates - closed candle handling - reconnect with
backoff - resubscription - REST reconciliation after reconnect

Deduplicate candles by open time.

## Phase 4 --- Indicators

Implement and test: - EMA 10/50/200 - RSI14 - MACD12/26/9 -
Bollinger20/2 - volume SMA20 - volume ratio

## Phase 5 --- Structure/CSD

Implement configurable pivot detection:

``` yaml
left_bars: 3
right_bars: 3
```

Track HH/HL/LH/LL.

Bullish CSD = meaningful swing-high break confirmed by a closed candle.

Bearish CSD = meaningful swing-low break confirmed by a closed candle.

Reject wick-only breaks.

## Phase 6 --- Breakout/retest

Implement the state machine:

``` text
IDLE
SETUP_DETECTED
CSD_DETECTED
BREAKOUT_CONFIRMED
WAITING_FOR_RETEST
RETEST_DETECTED
CONFIRMATION_PENDING
SIGNAL_CONFIRMED
INVALIDATED
```

Retest must return to the dynamic broken level and demonstrate a
reaction/hold.

## Phase 7 --- Confirmation/scoring

Score:

``` text
CSD       +2
Breakout  +2
Retest    +2
EMA       +1
RSI       +1
MACD      +1
Volume    +1
```

Thresholds:

``` text
0–4 no trade
5–6 watch
7–8 good
9–10 strong
```

Only \>=7 sends a confirmed signal.

## Phase 8 --- Risk

Calculate dynamically: - entry zone - reference entry -
structure/ATR-buffered SL - TP1 1R - TP2 2R - TP3 3R - TP4 major
structure level - R:R

Never use fixed prices from examples.

## Phase 9 --- Notifications

Create a provider interface and implement: - WhatsApp official
Business/Cloud API-compatible adapter - Discord webhook - Push provider
adapter - SMTP/email

Each provider is independent.

Use environment variables.

## Phase 10 --- Persistence

Implement SQLite repositories and migrations for: - candles - signals -
signal_events - notifications

Make signal IDs unique.

Prevent duplicate alerts.

## Phase 11 --- Replay

Implement historical replay using the same strategy classes as live
mode.

## Phase 12 --- Tests

Write deterministic tests for every critical component.

At minimum: - swings - structure - bullish/bearish CSD - wick
rejection - breakout - retest - confirmation - scoring - target
calculation - state machine - duplicate prevention - notification
failure isolation - reconnect/reconciliation

## Phase 13 --- Deployment

Create/update: - `.env.example` - `.gitignore` - Dockerfile -
docker-compose.yml - README - health check

## Phase 14 --- Security audit

Search source for credentials, tokens, passwords and hard-coded webhook
URLs.

Confirm: - no trading endpoint - no order code - no withdrawal code - no
secrets in Git - no secrets in logs

## Phase 15 --- Verification

Run the full test suite.

Then simulate: 1. bullish CSD 2. bearish CSD 3. failed wick breakout 4.
successful retest 5. failed retest 6. duplicate signal 7. notification
provider outage 8. WebSocket reconnect 9. restart/persistence

Do not claim completion until verification passes.

## Final response

Return: - implementation summary - files created - files modified -
tests run/results - environment variables required - commands to run -
known limitations - next recommended step

**Do not implement V2 auto-trading.**
