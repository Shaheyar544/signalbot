# ETH CSD Signal Bot V1 --- Complete Technical Specification

## 1. Objective

Build a production-ready, signal-only monitoring service for **Binance
USD-M Futures, ETHUSDT Perpetual**.

Primary signal timeframe: **15M**. Confirmation timeframes: **1H and
4H**.

The strategy must follow:

`Structure → CSD/BOS → Breakout → Retest → Confirmation → Score → Alert`

When conditions are unclear, the correct result is **NO SIGNAL**.

## 2. Non-negotiable constraints

1.  V1 must never place trades.
2.  Do not require Binance trading API permissions.
3.  Never hard-code today's ETH levels.
4.  Use dynamically detected swing highs/lows.
5.  Confirm signals on closed 15M candles.
6.  Prevent duplicate alerts.
7.  Notification failure must never crash the strategy engine.
8.  Never log credentials/tokens.
9.  Live and historical replay must use the same strategy engine.
10. All thresholds must be configurable.

## 3. Architecture

``` text
Binance Futures REST/WebSocket
          ↓
Market Data Collector
          ↓
Candle Cache / Database
          ↓
Indicator Engine
          ↓
Swing + Market Structure Engine
          ↓
CSD Engine
          ↓
Breakout / Retest Engine
          ↓
Confirmation Engine
          ↓
Confidence Scoring
          ↓
Entry / SL / TP Calculator
          ↓
Signal State Machine
          ↓
Notification Dispatcher
     ├── WhatsApp
     ├── Discord
     ├── Push
     └── Email
```

## 4. Data

Required: - ETHUSDT USD-M perpetual - 15M candles - 1H candles - 4H
candles - OHLCV - current price

Optional V1 inputs: - Open Interest - Funding Rate

The bot must bootstrap historical candles through REST, then consume
live WebSocket updates. On reconnect it must re-fetch recent candles and
reconcile by candle open time.

## 5. Indicators

Calculate: - EMA 10 - EMA 50 - EMA 200 - RSI 14 - MACD 12/26/9 -
Bollinger Bands 20, 2 standard deviations - Volume SMA 20 - Volume ratio
= current volume / volume SMA20

Keep indicator implementations deterministic and unit-tested.

## 6. Swing detection

Default:

``` yaml
swing:
  left_bars: 3
  right_bars: 3
```

A swing high is a pivot whose high exceeds surrounding configured bars.
A swing low is the inverse.

Expose the parameters in configuration.

## 7. Market structure

Track: - HH --- Higher High - HL --- Higher Low - LH --- Lower High - LL
--- Lower Low

Bullish transition example:

`LL → HL → break previous swing high → HH`

Bearish transition:

`HH → LH → break previous swing low → LL`

The structure engine must retain recent structure events.

## 8. CSD/BOS definition

### Bullish CSD

A bullish CSD occurs when: 1. Recent structure is bearish/weak or a
meaningful reversal context exists. 2. A valid recent swing high exists.
3. A **closed 15M candle closes above that swing high**. 4. Break
distance passes a configurable minimum threshold. 5. It is not merely a
wick/liquidity sweep.

### Bearish CSD

Mirror the bullish rules around a meaningful swing low.

Example of invalid bullish CSD:

`high > swing high, but candle closes back below swing high`.

## 9. Breakout

Configurable example:

``` yaml
breakout:
  require_closed_candle: true
  minimum_close_distance_percent: 0.05
  volume_confirmation: optional
```

Prefer ATR-based thresholds in a future enhancement.

## 10. Retest

After a confirmed breakout, wait for price to return to the broken
level.

``` yaml
retest:
  zone_percent: 0.20
  maximum_bars_after_breakout: 12
```

A simple touch is insufficient. Require a meaningful hold/rejection.

Bullish: `break resistance → return to zone → hold → bullish reaction`

Bearish: `break support → return to zone → reject → bearish reaction`

## 11. Confirmation

### Long required

-   bullish CSD
-   breakout confirmed
-   retest detected
-   retest holds

### Long supporting

-   price above/reclaiming EMA10
-   EMA10 \> EMA50 preferred
-   RSI \>= 50 preferred
-   MACD histogram improving/positive
-   supportive volume
-   1H not strongly bearish
-   4H not strongly bearish

### Short

Mirror the logic.

Supporting conditions are scored; do not make every indicator mandatory.

## 12. Confidence score

  Condition         Points
  --------------- --------
  CSD                   +2
  Breakout              +2
  Retest                +2
  EMA alignment         +1
  RSI                   +1
  MACD                  +1
  Volume                +1

Maximum: 10.

``` text
0–4  NO TRADE
5–6  WATCH
7–8  GOOD SIGNAL
9–10 STRONG SIGNAL
```

Only score \>= 7 creates a confirmed alert.

## 13. State machine

``` text
IDLE
 ↓
SETUP_DETECTED
 ↓
CSD_DETECTED
 ↓
BREAKOUT_CONFIRMED
 ↓
WAITING_FOR_RETEST
 ↓
RETEST_DETECTED
 ↓
CONFIRMATION_PENDING
 ↓
SIGNAL_CONFIRMED
```

Failure states: - INVALIDATED - BREAKOUT_FAILED - RETEST_FAILED

Do not reset into a new signal from the same event without a new
structure trigger.

## 14. Duplicate prevention

Generate a stable signal ID, for example:

`ETHUSDT-15M-LONG-<structure_timestamp>-<breakout_level>`

Persist IDs.

Default cooldown:

``` yaml
alerts:
  duplicate_cooldown_minutes: 60
```

Allowed follow-up events: - signal confirmed - TP1/TP2/TP3 reached -
SL/invalidation - setup cancelled

## 15. Entry

Use the dynamic retest zone.

Signal object must contain: - entry_low - entry_high - reference_entry -
breakout_level - retest_level

Never substitute hard-coded prices.

## 16. Stop loss

Structure-based: - LONG: below retest/swing low - SHORT: above
retest/swing high

Suggested configurable ATR buffer:

``` yaml
risk:
  stop_buffer_atr: 0.25
```

## 17. Take profits

Default risk-multiple framework:

`R = abs(reference_entry - stop_loss)`

-   TP1 = 1R
-   TP2 = 2R
-   TP3 = 3R
-   TP4 = next major structure level

The engine must check nearby major structure so targets are not blindly
placed through obvious resistance/support.

## 18. Canonical signal model

``` json
{
  "signal_id": "ETHUSDT-15M-LONG-<timestamp>",
  "symbol": "ETHUSDT",
  "market": "USD-M-FUTURES",
  "timeframe": "15m",
  "direction": "LONG",
  "status": "CONFIRMED",
  "confidence": 9,
  "entry": {"low": 0, "high": 0, "reference": 0},
  "stop_loss": 0,
  "take_profits": [0, 0, 0, 0],
  "risk_reward": {"tp1": 1, "tp2": 2, "tp3": 3},
  "confirmation": {
    "csd": true,
    "breakout": true,
    "retest": true,
    "ema": true,
    "rsi": true,
    "macd": true,
    "volume": false
  },
  "timestamp": "ISO-8601"
}
```

## 19. Notifications

Use an adapter pattern:

``` python
class NotificationProvider(Protocol):
    async def send_signal(self, signal: Signal) -> NotificationResult: ...
```

Implement: - WhatsAppProvider - DiscordProvider - PushProvider -
EmailProvider

The dispatcher calls all enabled providers independently.

### WhatsApp

Use an official WhatsApp Business/Cloud API-compatible method. Never
automate WhatsApp Web or scrape it.

Environment variables:

``` env
WHATSAPP_ENABLED=true
WHATSAPP_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_RECIPIENT=
```

### Discord

V1 can use a webhook:

``` env
DISCORD_ENABLED=true
DISCORD_WEBHOOK_URL=
```

### Push

Use a provider such as Firebase Cloud Messaging or another supported
push service behind an adapter.

### Email

SMTP or transactional provider:

``` env
EMAIL_ENABLED=true
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
EMAIL_FROM=
EMAIL_TO=
```

Provider failures must be isolated and retried with bounded exponential
backoff.

## 20. Standard alert

``` text
🟢 ETHUSDT LONG CONFIRMED

Confidence: 9/10
Timeframe: 15M

ENTRY
<dynamic low> – <dynamic high>

STOP LOSS
<dynamic SL>

TAKE PROFIT
TP1 <dynamic>
TP2 <dynamic>
TP3 <dynamic>
TP4 <dynamic>

CONFIRMATION
CSD       ✅
Breakout  ✅
Retest    ✅
EMA       ✅
RSI       ✅
MACD      ✅
Volume    ❌

R:R
TP1 1.0R
TP2 2.0R
TP3 3.0R

Signal only — no trade executed.
```

## 21. Database

SQLite for V1/local; design repositories for PostgreSQL later.

Tables:

### candles

`id, symbol, timeframe, open_time, open, high, low, close, volume, closed, created_at`

### signals

`id, signal_id, symbol, timeframe, direction, status, confidence, entry_low, entry_high, entry_reference, stop_loss, tp1, tp2, tp3, tp4, breakout_level, retest_level, created_at, updated_at`

### signal_events

`id, signal_id, event_type, payload, created_at`

### notifications

`id, signal_id, provider, status, attempts, error, sent_at, created_at`

## 22. Project structure

``` text
eth-csd-signal-bot/
├── app/
│   ├── main.py
│   ├── config/
│   │   ├── settings.py
│   │   └── config.yaml
│   ├── data/
│   │   ├── binance_rest.py
│   │   ├── binance_ws.py
│   │   ├── candles.py
│   │   └── cache.py
│   ├── indicators/
│   │   ├── ema.py
│   │   ├── rsi.py
│   │   ├── macd.py
│   │   ├── bollinger.py
│   │   └── volume.py
│   ├── structure/
│   │   ├── swings.py
│   │   ├── market_structure.py
│   │   └── csd.py
│   ├── strategy/
│   │   ├── breakout.py
│   │   ├── retest.py
│   │   ├── confirmation.py
│   │   ├── scoring.py
│   │   └── targets.py
│   ├── signals/
│   │   ├── state_machine.py
│   │   ├── signal_manager.py
│   │   └── models.py
│   ├── notifications/
│   │   ├── base.py
│   │   ├── whatsapp.py
│   │   ├── discord.py
│   │   ├── push.py
│   │   ├── email.py
│   │   └── dispatcher.py
│   ├── storage/
│   │   ├── database.py
│   │   ├── repositories.py
│   │   └── migrations/
│   └── monitoring/
│       ├── health.py
│       └── metrics.py
├── tests/
├── scripts/
│   ├── replay.py
│   └── health_check.py
├── .env.example
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## 23. Testing

Required tests: - swing highs/lows - HH/HL/LH/LL - bullish CSD - bearish
CSD - wick-only breakout rejection - breakout - retest - confirmation -
scoring - targets - state transitions - duplicate prevention - provider
failure isolation - WebSocket reconnect - historical reconciliation -
restart persistence

Create deterministic candle fixtures.

## 24. Historical replay

Implement `scripts/replay.py`.

Feed historical candles chronologically through the **same strategy
engine used in live mode**.

Record: - signal count - direction - timestamp - confidence - entry -
SL - TP - outcome - R achieved - maximum favorable excursion - maximum
adverse excursion

## 25. Health

Track: - WebSocket connected - last candle - last evaluation - last
signal - notification status - database status - uptime

If data becomes stale, pause signal generation and issue a controlled
health warning.

## 26. Security

-   secrets only in environment variables
-   `.env` in `.gitignore`
-   no secrets in logs
-   no source-code credentials
-   no trading permissions in V1
-   no withdrawal permissions
-   no API secrets pasted into chat

## 27. Docker/VPS

Support Docker with: - restart policy - persistent database volume -
environment configuration - stdout logging

For 24/7 monitoring use a Linux VPS/cloud server. The phone is only the
notification endpoint.

## 28. Acceptance criteria

V1 is complete only when: - market bootstrap works - 15M/1H/4H feeds
work - indicators are tested - dynamic swing detection works -
bullish/bearish CSD works - breakout/retest works - score works -
dynamic Entry/SL/TP works - state machine works - duplicate prevention
works - all four notification adapters work - provider failures are
isolated - WebSocket reconnect works - historical replay works -
database persists state - tests pass - Docker works - no trading/order
execution exists

## 29. Future V2 --- not part of implementation

Potential: - BTCUSDT - XAUUSD - multiple timeframes - OI/funding -
liquidity sweeps - FVG/order blocks - dynamic ATR zones - chart
snapshots - web dashboard - paper trading - optional auto-trading with
separate safety architecture
