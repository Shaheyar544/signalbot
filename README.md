# Multi-Pair CSD Signal Engine — Phase 1

## Purpose

Signal-only ETHUSDT Perpetual monitoring bot. It analyzes 15M
structure/CSD, uses 1H and 4H confirmation, calculates Entry/SL/TP and a
0--10 confidence score, then sends confirmed alerts through WhatsApp,
Discord, Push Notifications and Email.

## Documents

-   `ETH-CSD-SIGNAL-BOT-SPEC.md` --- complete technical specification.
-   `CODEX-IMPLEMENTATION-PROMPT.md` --- copy/paste implementation
    instructions for Codex.
-   `DEPLOYMENT-OPERATIONS-GUIDE.md` --- setup and production
    operations.

## V1 safety boundary

**No Binance order placement. No automatic trading. No withdrawal
functionality.**

## Implemented foundations

The repository provides a production-oriented market-data foundation and Phase 2 analysis domain. It uses public Binance USD-M Futures REST and WebSocket endpoints, persists OHLCV data in SQLite, and evaluates only closed primary-timeframe candles.

Phase 2 includes deterministic EMA, RSI, MACD, Bollinger Bands, and volume calculations; configurable pivot detection; HH/HL/LH/LL classification; and closed-candle CSD analysis. It does not contain breakout/retest logic, scoring, notifications, account access, or trading code.

The current setup lifecycle also creates a pending breakout after a CSD, evaluates configurable retest zones on subsequent closed candles, and records detected retests, invalidations, or expired setups. It still does not calculate entries, stops, targets, confidence scores, notifications, account access, or trading code.

Completed setup assessments include configurable EMA/RSI/MACD/volume evidence, 1h and 4h context, and a transparent 0–10 score classified as `NO_TRADE`, `WATCH`, `GOOD_SIGNAL`, or `STRONG_SIGNAL`. An assessment is analysis only: it does not send a notification, calculate risk, or execute a trade.

For `GOOD_SIGNAL` and `STRONG_SIGNAL` assessments, the engine also derives a dynamic retest-zone entry reference, a structure-based buffered stop, TP1/TP2/TP3 at 1R/2R/3R, an optional TP4 from the nearest opposing structure level, and the risk-unit distance. These are informational reference values only.

Qualifying analysis snapshots persist to SQLite with a stable signal ID. Duplicate IDs are ignored safely. `app.replay.HistoricalReplay` can feed a chronological closed-candle sequence through the same strategy interface used in live mode.

Optional notification adapters are disabled by default. Copy `.env.example` to `.env`, configure only the provider(s) you choose, and load those environment variables in your deployment environment. Provider failures are isolated and recorded in SQLite; they never affect analysis or trading because the engine has no trading capability.

Requirements: Python 3.12+.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.main --config config.yaml
```

Run tests:

```powershell
pytest
```

## Local monitoring dashboard

The dashboard is a separate, read-only local web process. In a second Laragon
terminal, with the virtual environment activated, run:

```powershell
python -m app.dashboard --config config.yaml
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000). It displays the
database connection, configured enabled symbols, persisted signal records,
recent candles, and the engine's live WebSocket/last-closed-candle health.
Restart the engine after updating the project so it begins publishing its
runtime-health snapshot. The dashboard refreshes every 15 seconds.
Its JSON endpoints also expose recent candles and signals for local monitoring:
`/api/status`, `/api/candles`, `/api/signals`, and `/api/notifications`.
The dashboard has no trading controls and does not access Binance private APIs.

Run with Docker (after copying `.env.example` to `.env`; providers remain disabled unless explicitly enabled):

```powershell
docker compose up --build -d
docker compose logs -f signal-engine
docker compose exec signal-engine python scripts/health_check.py --database /app/data/signal_engine.db
```

The named `signal_data` volume retains SQLite data across container restarts. Stop the service with `docker compose down`; do not use `-v` unless intentionally removing persisted data.

`config.yaml` controls symbols. To enable BTCUSDT (or another supported USD-M Futures symbol), add/configure the symbol and set `enabled: true`; no code changes are required. The engine validates every enabled symbol against Binance and skips invalid or unsupported symbols without stopping the other streams.

## Research validation

Run the unified, read-only research report against stored historical candles:

```powershell
python scripts\run_phase9_validation.py --config config.yaml --sensitivity path\to\approved-sensitivity.json --report data\research_report.json --csv data\research_summary.csv
```

It reuses the canonical strategy, exit policy, and cost model. The versioned
JSON report includes baseline, score bands, HTF variants, calendar
walk-forward, approved sensitivity observations, Monte Carlo trade-order risk,
leave-one-symbol-out results, cost stresses, lifecycle-data availability,
reproducibility metadata, and the conservative go-live gate result. It never
places orders or changes production strategy settings. A non-zero exit status
means the report is incomplete, not that the strategy has failed or succeeded.

Research semantics are explicit: Monte Carlo shuffles completed trade order to
measure sequence drawdown/streak risk only—total R is invariant and it is not
entry-edge evidence. Percentiles use the deterministic nearest-rank convention.
Cost stress requires recorded entry time, exit time, and actual exit price;
legacy audits missing those fields are reported as `INCOMPLETE_DATA`. Lifecycle
conversion requires persisted events linked to the same setup/signal entity;
unlinked or absent lifecycle records are reported as unavailable rather than
estimated.

Cost assumptions are percentages of trade notional, then expressed as initial
stop-risk R. Consequently, the same fee/slippage percentage is a larger R cost
for a tighter stop; reports do not cap or hide that economic effect. Frozen V1
classification is executable and consistent across live/replay/reporting:
`NO_TRADE < 3.0`, `WATCH 3.0–<5.0`, `GOOD_SIGNAL 5.0–<7.5`, and
`STRONG_SIGNAL >= 7.5`; only the latter two are signal-eligible.
