# ETH CSD Signal Bot V1 --- Deployment & Operations Guide

## 1. Required services

-   Binance public market data
-   WhatsApp Business/Cloud API-compatible provider
-   Discord webhook
-   Push notification provider
-   SMTP/email
-   Linux VPS/cloud host for 24/7 operation

V1 does not require Binance trading credentials.

## 2. Environment

Create `.env` from `.env.example`.

``` env
APP_ENV=production
LOG_LEVEL=INFO
BINANCE_SYMBOL=ETHUSDT

WHATSAPP_ENABLED=true
WHATSAPP_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
WHATSAPP_RECIPIENT=

DISCORD_ENABLED=true
DISCORD_WEBHOOK_URL=

PUSH_ENABLED=true
PUSH_PROVIDER=
PUSH_API_KEY=
PUSH_DEVICE_TOKEN=

EMAIL_ENABLED=true
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
EMAIL_FROM=
EMAIL_TO=
```

Never commit `.env`.

## 3. First-run procedure

1.  Install dependencies.
2.  Configure environment.
3.  Test database.
4.  Test each notification provider independently.
5.  Start signal-only mode.
6.  Verify historical bootstrap.
7.  Verify WebSocket connection.
8.  Wait for closed 15M candles.
9.  Verify alerts against the chart manually.

A period with no signals is normal.

### Docker deployment

1. Copy `.env.example` to `.env` and leave every provider disabled until its configuration is complete.
2. Review `config.yaml`; ETHUSDT is the sole enabled default pair.
3. Start with `docker compose up --build -d`.
4. Follow logs using `docker compose logs -f signal-engine`.
5. Check SQLite readiness with `docker compose exec signal-engine python scripts/health_check.py --database /app/data/signal_engine.db`.

The `signal_data` named volume retains SQLite data. `docker compose down` is safe; `docker compose down -v` intentionally removes the persisted database.

## 4. Expected signal sequence

``` text
Structure
→ CSD
→ Breakout
→ Retest
→ Confirmation
→ Score >= 7
→ Alert
```

No low-quality alert should be generated merely because RSI/EMA/MACD
changes.

## 5. Notification test

Expected:

``` text
WhatsApp → TEST PASSED
Discord  → TEST PASSED
Push     → TEST PASSED
Email    → TEST PASSED
```

One provider failing must not stop the others.

## 6. Production deployment

Recommended:

``` text
Linux VPS
  ↓
Docker
  ↓
ETH Signal Bot
  ↓
Persistent DB
  ↓
WhatsApp / Discord / Push / Email
```

Use Docker restart policies and persistent storage.

## 7. Health monitoring

Monitor: - WebSocket connection - latest candle timestamp - strategy
evaluation - last signal - provider delivery - database health - uptime

If data is stale, pause signals and send a health warning.

## 8. Reviewing an alert

When a signal arrives: 1. Open the live chart. 2. Verify the current
price. 3. Verify the entry zone has not been missed. 4. Check 1H/4H
structure. 5. Do not chase price far outside the calculated entry. 6.
Treat the SL as the strategy invalidation level. 7. Remember that a
signal is not a guarantee.

## 9. Performance tracking

During signal-only validation record: - total signals - LONG/SHORT -
confidence distribution - TP1/TP2/TP3 results - SL events - R achieved -
maximum favorable excursion - maximum adverse excursion

Evaluate batches rather than changing rules after one trade.

## 10. Troubleshooting

### No signals

Possible causes: - no valid CSD - breakout not confirmed - retest
missing - confidence \<7 - higher timeframe conflict - stale data -
setup invalidated

### Duplicate alerts

Check: - signal ID - database uniqueness - state machine - cooldown

### Missing notifications

Check provider logs and credentials. Other providers should continue
working.

### WebSocket disconnect

The application should reconnect automatically and reconcile missed
candles.

## 11. Security

Never: - put secrets in source - commit `.env` - log tokens/passwords -
enable trading permissions for V1 - paste exchange secrets into chat

## 12. V1 completion gate

Do not move toward auto-trading until: - historical replay is tested -
live signal-only behavior is validated - paper trading has been
evaluated - risk controls are designed separately -
restart/reconciliation behavior is proven

Auto-trading is a separate V2 project.
