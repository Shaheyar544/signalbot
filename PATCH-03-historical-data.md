# Patch 03 — Multi-symbol historical data acquisition + integrity checks

Target repo: `signalbot`, state as of commit `4008b16` (PATCH-02 complete —
cost model, exit policy engine, single-pass trade lifecycle, 79/79 tests
passing, verified).

Scope: `app/data/binance_rest.py`, `app/storage/repositories.py`,
`app/config/settings.py`, `config.yaml`, new `scripts/fetch_historical.py`,
new `app/backtest/data_integrity.py`. Do not touch scoring, exits, costs, or
the live WebSocket path in this patch.

## Why this patch exists

Everything validated so far — swing gating, scoring, costs, exits — has been
proven correct on synthetic fixtures, a handful of candles at a time. None of
it has been run against real market data yet, and there isn't enough of it:
`fetch_candles()` in `BinanceRestClient` takes a single `limit` (max 1500 per
Binance's API) with no pagination, and `config.yaml` only enables ETHUSDT.
ETH 15M produces roughly 10–25 valid setups a month — a single year of one
symbol will not produce enough trades for the metrics engine (patch 4) or
walk-forward validation (patch 6) to say anything statistically meaningful.
This patch fetches 5 symbols × 3 years × 3 timeframes, persists it, and
verifies it's actually complete before anything downstream trusts it.

---

## Part E — Paginated historical fetch

### E1. Add range-based fetching to `BinanceRestClient`

`fetch_candles(symbol, timeframe, limit)` stays as-is (used by live bootstrap
— don't change its signature or behavior). Add a new method for bulk
historical acquisition:

```python
async def fetch_candles_range(self, symbol: str, timeframe: str,
                               start: datetime, end: datetime) -> list[Candle]:
    """Paginate /fapi/v1/klines with startTime/endTime to cover an arbitrary
    range. Binance returns at most 1500 candles per call; loop until the
    range is covered, advancing startTime to the last returned candle's
    close_time + 1ms each iteration."""
```

Requirements:

- Use `startTime`/`endTime` params (milliseconds since epoch) alongside
  `limit=1500`.
- Loop: request, extend the result list, advance `start` to
  `last_returned.close_time + 1ms`. Stop when a response returns fewer than
  1500 rows (end of available data) or `start >= end`.
- Deduplicate by `open_time` across pages (a boundary candle can appear twice
  if timing is off by one).
- Rate limiting: reuse the existing `ReconnectBackoff` class from
  `app/data/binance_ws.py` (import it, don't duplicate the exponential-backoff
  logic) — on an HTTP 429 or 418, read `Retry-After` if present, otherwise use
  `ReconnectBackoff.next_delay()`, sleep, and retry the same page. Reset the
  backoff after a successful page. Add a small fixed delay (e.g. 250ms)
  between successful pages regardless, to stay well under Binance's weight
  limits when pulling years of data across 5 symbols.
- Raise (don't silently swallow) after some bounded number of consecutive
  failures per page — define a `max_consecutive_failures` (e.g. 5) so a
  persistent outage doesn't spin forever.

### E2. Bulk persistence

`CandleRepository.upsert()` commits once per candle — fine for live
trading, far too slow for ~105,000 candles per symbol/timeframe (3 years of
15M) times 5 symbols times 3 timeframes. Add:

```python
def upsert_many(self, candles: Sequence[Candle]) -> None:
    """Single transaction, executemany, one commit."""
```

Keep `upsert()` for the live single-candle path unchanged; `upsert_many` is
new, used only by the historical fetch script.

Also add a read-back method, since nothing currently loads persisted candles
into memory for backtest use:

```python
def load_range(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[Candle]:
    """Read persisted candles back as Candle objects, ordered by open_time."""
```

### E3. Config

Add `XRPUSDT` to `config.yaml`'s `symbols:` section (currently ETHUSDT,
BTCUSDT, SOLUSDT, BNBUSDT — four; the validation plan needs five for adequate
sample size across correlated majors). Leave all five `enabled: false` except
ETHUSDT for live/alerting purposes — historical fetching for backtest
purposes should be independent of the live `enabled` flag. Add a new
top-level `historical:` config section:

```yaml
historical:
  symbols: [ETHUSDT, BTCUSDT, SOLUSDT, BNBUSDT, XRPUSDT]
  years: 3
  timeframes: [15m, 1h, 4h]
```

Wire a `HistoricalDataSettings` dataclass into `Settings`/`load_settings()`
following the existing pattern (validate `years > 0`, all symbols pass
`normalize_symbol()`, all timeframes are in `SUPPORTED_TIMEFRAMES`).

### E4. `scripts/fetch_historical.py`

New script, following the pattern of the existing `scripts/health_check.py`.
Responsibilities:

- Load settings, open the database.
- For each symbol × timeframe in `historical`, compute the start/end range
  (`end = now`, `start = now - years`), call `fetch_candles_range`, and
  `upsert_many` the result in batches (e.g. every 5,000 candles, to avoid
  holding the entire 3-year series in memory for all 15 symbol/timeframe
  pairs at once — process and flush one symbol/timeframe pair fully before
  moving to the next).
- Print progress per symbol/timeframe: candles fetched, date range covered,
  elapsed time.
- After each symbol/timeframe finishes, immediately run the integrity check
  (Part F) against what's now persisted and print the result inline, so a
  problem in symbol 1 is visible before spending an hour fetching symbols 2–5.
- Exit with a nonzero status code if any symbol/timeframe fails integrity
  checks after fetching, and print a summary table at the end (symbol,
  timeframe, candle count, gap count, status).
- Must be resumable: if run again, `upsert_many`'s `ON CONFLICT` upsert
  behavior means re-fetching an already-covered range is safe and just
  re-verifies rather than duplicating. Support a `--symbol`/`--timeframe` CLI
  flag to re-run a single pair without refetching everything, for when only
  one pair fails integrity and needs a retry.

### E5. Required tests

`tests/test_binance_rest_pagination.py`: mock the HTTP layer (the existing
tests likely already have a pattern for mocking `aiohttp` responses in
`tests/test_rest.py` — follow it) and assert:

- A range requiring 3 pages (e.g. 4,000 candles at limit 1500) makes exactly 3
  requests and returns all candles in order, deduplicated.
- A 429 response triggers a backoff-and-retry rather than raising immediately.
- Exceeding `max_consecutive_failures` raises.

`tests/test_candle_repository_bulk.py`: `upsert_many` followed by
`load_range` round-trips correctly; re-running `upsert_many` on overlapping
data doesn't create duplicate rows (verify via `count(*)` against the unique
constraint); a large batch (e.g. 10,000 synthetic candles) completes without
per-row commits (this can be asserted indirectly by timing, or by mocking
`connection.commit` and asserting it's called once, not N times).

---

## Part F — Data integrity checking

### F1. `app/backtest/data_integrity.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from app.events.models import Candle
from app.structure.timeframes import duration  # from PATCH-01


@dataclass(frozen=True)
class IntegrityGap:
    symbol: str
    timeframe: str
    expected_after: datetime
    actual_next: datetime
    missing_candles: int


@dataclass(frozen=True)
class IntegrityReport:
    symbol: str
    timeframe: str
    candle_count: int
    range_start: datetime | None
    range_end: datetime | None
    gaps: tuple[IntegrityGap, ...]
    duplicate_open_times: int
    ohlc_violations: int

    @property
    def is_clean(self) -> bool:
        return not self.gaps and self.duplicate_open_times == 0 and self.ohlc_violations == 0


def check_integrity(symbol: str, timeframe: str, candles: Sequence[Candle]) -> IntegrityReport:
    """Pure function: given a candle series, report gaps, duplicates, and OHLC
    violations. Does not fetch or fix anything — the fetch script decides what
    to do with the report."""
```

Requirements for `check_integrity`:

- Sort by `open_time`. For each consecutive pair, the expected next
  `open_time` is `previous.open_time + duration(timeframe)`. If the actual
  next candle's `open_time` is later than expected, record an `IntegrityGap`
  with `missing_candles = (actual - expected) / duration(timeframe)`.
- Duplicate `open_time` values (shouldn't happen given the DB's unique
  constraint, but check anyway — this function operates on a plain sequence,
  not necessarily DB-sourced, e.g. it should also be usable directly on
  REST-fetched data before persistence).
- OHLC violations: candles failing `Candle.__post_init__`'s invariants would
  already raise at construction, so this field will typically be `0` for
  DB-round-tripped data — include it anyway for defense against manual data
  edits and to make the report self-contained.
- Small gaps (1–2 missing candles) can legitimately happen from brief
  exchange downtime; don't treat every gap as fatal in the summary — but
  report every gap regardless of size, and let the caller (fetch script)
  decide a threshold for failing the run (e.g. "any gap over 3 consecutive
  missing candles fails integrity" is a reasonable default — make this
  configurable, don't hard-code it inside `check_integrity` itself).

### F2. Required tests

`tests/test_data_integrity.py`:

- A complete, gapless series of candles produces `is_clean == True` and zero
  gaps.
- A series with one deliberately removed candle in the middle produces
  exactly one `IntegrityGap` with `missing_candles == 1`.
- A series with a duplicated `open_time` (construct two candles with the same
  `open_time` but different data, bypassing the DB's constraint by testing the
  pure function directly) is caught by `duplicate_open_times`.
- Multiple gaps in one series are all reported, not just the first.
- An empty candle sequence doesn't crash — returns a report with
  `candle_count == 0` and no gaps.

---

## Acceptance for this patch

- Actually run `scripts/fetch_historical.py` against live Binance data for at
  least ETHUSDT (the other 4 symbols can follow once ETHUSDT's run is
  confirmed clean — don't burn hours of fetch time on 5 symbols before
  confirming the pagination logic is correct on one). Report actual candle
  counts fetched per timeframe and actual wall-clock time taken.
- Report the integrity check result for whatever was actually fetched —
  real gap count, real date range, not a synthetic test result standing in
  for it.
- If ETHUSDT's fetch is clean, proceed to BTCUSDT, SOLUSDT, BNBUSDT, XRPUSDT
  and report the same for each.
- Full test suite passes, including the new pagination, bulk-repository, and
  integrity tests.
- State clearly, per symbol/timeframe: candle count, date range actually
  covered, gap count, and whether it passes your chosen gap-severity
  threshold.
- Do not start the metrics engine, random baseline, or walk-forward in this
  patch — those depend on this data existing and being verified first. Stop
  here for review once all 5 symbols × 3 timeframes are fetched and reported.
