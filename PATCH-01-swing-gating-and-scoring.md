# Patch 01 — Explicit swing confirmation gating + replace degenerate scoring

Target repo: `signalbot` (main branch, current state as reviewed).
Scope: only the files listed below. Do not touch notifications, dashboard,
data collection, or Docker in this patch.

This patch does two independent things. Do them in order; run tests after each.

---

## Part A — Explicit `confirmed_time` swing gating

### Why

`CandleStore.get_recent_as_of()` in `app/data/candles.py` already bounds every
read to `open_time <= as_of`, and `SwingDetector.detect()` only emits a pivot
once it has `right_bars` trailing candles in the array it receives. Combined,
this already prevents look-ahead in practice — but the invariant is implicit.
Nothing stops a future caller from passing `SwingDetector.detect()` an
unbounded candle list and silently reintroducing leakage. Make the invariant
explicit and independently testable.

### A1. Add a timeframe duration helper

New file `app/structure/timeframes.py`:

```python
from __future__ import annotations

from datetime import timedelta

_DURATIONS = {
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
}


def duration(timeframe: str) -> timedelta:
    try:
        return _DURATIONS[timeframe]
    except KeyError as error:
        raise ValueError(f"Unknown timeframe: {timeframe!r}") from error
```

### A2. Add `confirmed_time` to `SwingPoint`

In `app/structure/swings.py`:

- Import `duration` from `app.structure.timeframes`.
- Add a field `confirmed_time: datetime` to `SwingPoint`.
- In `SwingDetector.detect()`, when constructing each `SwingPoint`, compute:

```python
confirmed_time = candidate.close_time + duration(candidate.timeframe) * self.right_bars
```

  (Use `close_time`, not `open_time`, as the base — a pivot at bar `i` is only
  confirmable once the `right_bars`-th candle *after* it has closed.)

- Keep `detect()`'s existing signature and behavior unchanged otherwise — it
  still returns all swings it can find in the array it's given. The gating
  responsibility moves to a new accessor (A3), not into `detect()` itself.

### A3. Add a gated store and retire raw list access

New file `app/structure/swing_store.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Sequence

from app.structure.swings import SwingPoint


class SwingStore:
    """The only sanctioned read path for swing data. Enforces confirmed_time gating."""

    def __init__(self) -> None:
        self._swings: list[SwingPoint] = []

    def replace(self, swings: Sequence[SwingPoint]) -> None:
        """Called once per candle-close with the detector's full output for
        the bounded candle window. Overwrites, since detect() is idempotent
        over its input window."""
        self._swings = list(swings)

    def get_swings(self, as_of: datetime) -> list[SwingPoint]:
        return [swing for swing in self._swings if swing.confirmed_time <= as_of]
```

- `replace()` exists because `SwingDetector.detect()` is stateless and
  recomputes over whatever window it's given each call (see
  `CSDStrategyEngine.on_candle_closed`, which calls `self.swings.detect(candles)`
  fresh every time). `SwingStore` is the thin stateful wrapper that adds the
  `as_of` filter on top.

### A4. Wire it into `CSDStrategyEngine`

In `app/strategy/csd_strategy.py`:

- Import `SwingStore`.
- In `__init__`, add `self.swing_store = SwingStore()`.
- In `on_candle_closed`, replace:

  ```python
  structure = self.structure.evaluate(event.symbol, event.timeframe, self.swings.detect(candles))
  ```

  with:

  ```python
  self.swing_store.replace(self.swings.detect(candles))
  visible_swings = self.swing_store.get_swings(as_of=event.candle.close_time)
  structure = self.structure.evaluate(event.symbol, event.timeframe, visible_swings)
  ```

- This is currently redundant with the existing `get_recent_as_of` bounding
  (both should agree), which is exactly the point: it's now checked twice by
  two independent mechanisms, and a leakage test can target the `SwingStore`
  directly without needing to construct a full strategy engine.

### A5. Required tests

New file `tests/test_swing_store.py`:

```python
from datetime import timedelta

from app.structure.swing_store import SwingStore
from app.structure.swings import SwingDetector, SwingType
from dataclasses import replace as dc_replace
from decimal import Decimal


def _with_high(candle, high):
    return dc_replace(candle, high=Decimal(str(high)))


def test_swing_not_visible_before_confirmation(make_candle):
    candles = [_with_high(make_candle(offset=i), h) for i, h in enumerate((2, 3, 7, 3, 2))]
    detector = SwingDetector(left_bars=2, right_bars=2)
    store = SwingStore()
    store.replace(detector.detect(candles))

    pivot = next(s for s in store.get_swings(as_of=candles[-1].close_time) if s.kind is SwingType.HIGH)

    # Pivot is at candles[2]; right_bars=2 means it confirms at candles[4]'s close.
    assert store.get_swings(as_of=candles[2].close_time) == []
    assert store.get_swings(as_of=candles[3].close_time) == []
    assert pivot in store.get_swings(as_of=candles[4].close_time)


def test_replay_engine_has_no_future_access(make_candle):
    """Truncating the candle feed after the signal bar must not change the signal."""
    from app.data.candles import CandleStore
    from app.strategy.csd_strategy import CSDStrategyEngine
    from app.events.models import CandleClosedEvent

    # Build a longer synthetic series (reuse existing breakout/retest fixtures
    # from tests/test_breakout_retest.py if available) and run the engine
    # twice: once on the full series, once with everything after the expected
    # signal candle deleted. Assert identical CSD/retest/assessment output.
    # Implementation detail: parametrize against the existing fixture series
    # used in test_strategy_engine.py rather than duplicating candle setup.
    pass  # fill in using the project's existing engine-level fixtures


def test_indicator_excludes_forming_candle(make_candle):
    from app.indicators.engine import IndicatorEngine

    closed = [make_candle(offset=i, closed=True) for i in range(30)]
    forming = make_candle(offset=30, closed=False, close="999999")

    engine = IndicatorEngine()
    baseline = engine.calculate(closed)
    with_forming = engine.calculate([*closed, forming])

    assert with_forming.ema == baseline.ema
    assert with_forming.rsi == baseline.rsi
    assert with_forming.macd == baseline.macd
```

Note: `test_replay_engine_has_no_future_access` is left as a stub with
instructions rather than fully written, because it needs the project's actual
multi-candle CSD/breakout/retest fixture series (already built for
`tests/test_strategy_engine.py` and `tests/test_breakout_retest.py`) to be
meaningful — reuse those fixtures rather than inventing a new synthetic series.
Do not mark this patch complete until this test is filled in and passing.

Also confirm `IndicatorEngine.calculate()` already excludes non-closed candles
(check `app/indicators/engine.py` — the report says this is "mostly
implemented"). If it currently accepts and uses unclosed candles, filter them
out at the top of `calculate()`.

---

## Part B — Replace `setup_valid` / `confluence_score` with graded scoring

### Why

`app/strategy/scoring.py` currently has `setup_valid = has_csd and has_breakout
and has_retest` as a mandatory boolean gate, with only 4 optional binary points
(ema/rsi/macd/volume) actually varying. This is the same degenerate scoring
problem the original V1 spec had, renamed. `WATCH` is only reachable when
`confluence_score == 0`, which is nearly impossible in ordinary use since it
requires every one of four indicators to disagree. Replace with graded floats
so the score has real discriminating range, and so `NO_TRADE`/`WATCH` bands are
actually reachable by degree of quality, not just by mandatory-gate pass/fail.

### B1. Grade the confirmation inputs instead of returning booleans

In `app/strategy/confirmation.py`, keep `ConfirmationResult`'s existing boolean
fields (other code depends on them — e.g. `backtest_runner.py` doesn't, but
check for other readers) but add graded companion fields:

```python
@dataclass(frozen=True)
class ConfirmationResult:
    direction: CSDDirection
    ema: bool
    rsi: bool
    macd: bool
    volume: bool
    one_hour: bool
    four_hour: bool
    # New graded fields, each in [0, 1]:
    ema_quality: Decimal
    rsi_quality: Decimal
    macd_quality: Decimal
    volume_quality: Decimal
    htf_quality: Decimal
```

Grading rules (implement as private methods on `ConfirmationEngine`, mirroring
the existing `_aligned`/`_rsi_supports`/`_macd_supports` pattern):

- `ema_quality`: normalized EMA10-vs-EMA50 separation as a fraction of price,
  clipped to `[0, 1]` at some configurable saturation point (e.g. 0.5% = full
  score). Reuse the direction check from `_aligned` as the sign gate — if
  misaligned, quality is `0`, not negative.
- `rsi_quality`: `abs(rsi - 50) / 50` when RSI is on the supportive side of 50
  for the direction, else `0`.
- `macd_quality`: normalized histogram magnitude relative to recent histogram
  range (or relative to price if simpler — pick one and document it), `0` when
  histogram sign opposes direction.
- `volume_quality`: `min((volume_ratio - 1) / (volume_ratio_minimum), 1)`
  clipped to `[0, 1]`, `0` when ratio is `None` or below 1.
- `htf_quality`: `1.0` if both 1H and 4H `_not_strongly_opposed` are true,
  `0.5` if exactly one is true, `0.0` if neither.

Add a `weights` config (see B3) rather than hard-coding the saturation
constants inline — put them in `app/config/settings.py` under a new
`ScoringSettings` dataclass, following the existing pattern of
`ConfirmationSettings`/`RiskSettings`.

### B2. Grade CSD, breakout, and retest quality

These currently only exist as booleans (`has_csd`, `has_breakout`,
`has_retest` in `csd_strategy.py`, all hard-coded `True` when passed to
`scoring.score(...)` — check that call site, they're not even computed as
real quality signals today, just presence flags). Add:

- `CSDEvent` in `app/structure/csd.py` already carries `close_distance_percent`
  — use it directly: `csd_quality = min(close_distance_percent / saturation_percent, 1)`.
- `BreakoutStatus`/retest events in `app/strategy/breakout.py` and
  `app/strategy/retest.py` — check what data is available on the event objects
  (close position within candle range, bars-since-breakout, etc.) and expose a
  `quality: Decimal` field on each, following the same clipped-normalization
  pattern as A1. If the current event classes don't carry enough raw data to
  grade quality (e.g. no candle reference), add the fields needed rather than
  reconstructing them downstream.

### B3. Rewrite `ScoringEngine`

Replace `app/strategy/scoring.py` entirely:

```python
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from app.strategy.confirmation import ConfirmationResult


class SignalClassification(StrEnum):
    NO_TRADE = "NO_TRADE"
    WATCH = "WATCH"
    GOOD_SIGNAL = "GOOD_SIGNAL"
    STRONG_SIGNAL = "STRONG_SIGNAL"


@dataclass(frozen=True)
class ScoringWeights:
    csd: Decimal = Decimal("2.0")
    breakout: Decimal = Decimal("2.0")
    retest: Decimal = Decimal("2.0")
    ema: Decimal = Decimal("1.5")
    rsi: Decimal = Decimal("1.0")
    macd: Decimal = Decimal("1.0")
    volume: Decimal = Decimal("1.0")
    htf: Decimal = Decimal("1.5")


@dataclass(frozen=True)
class ConfidenceScore:
    total: Decimal                 # 0-10 continuous
    components: dict[str, Decimal]  # every graded input, for logging/audit
    classification: SignalClassification


class ScoringEngine:
    def __init__(self, weights: ScoringWeights | None = None,
                 threshold_watch: Decimal = Decimal("3.0"),
                 threshold_good: Decimal = Decimal("5.0"),
                 threshold_strong: Decimal = Decimal("7.5")) -> None:
        self.weights = weights or ScoringWeights()
        self.threshold_watch = threshold_watch
        self.threshold_good = threshold_good
        self.threshold_strong = threshold_strong

    def score(self, confirmation: ConfirmationResult, *,
              csd_quality: Decimal, breakout_quality: Decimal, retest_quality: Decimal) -> ConfidenceScore:
        w = self.weights
        components = {
            "csd": csd_quality * w.csd,
            "breakout": breakout_quality * w.breakout,
            "retest": retest_quality * w.retest,
            "ema": confirmation.ema_quality * w.ema,
            "rsi": confirmation.rsi_quality * w.rsi,
            "macd": confirmation.macd_quality * w.macd,
            "volume": confirmation.volume_quality * w.volume,
            "htf": confirmation.htf_quality * w.htf,
        }
        total = sum(components.values())
        if total < self.threshold_watch:
            classification = SignalClassification.NO_TRADE
        elif total < self.threshold_good:
            classification = SignalClassification.WATCH
        elif total < self.threshold_strong:
            classification = SignalClassification.GOOD_SIGNAL
        else:
            classification = SignalClassification.STRONG_SIGNAL
        return ConfidenceScore(total, components, classification)
```

Notes:

- Max possible total with default weights is `2+2+2+1.5+1+1+1+1.5 = 12`, not
  10. Either rescale (`total * 10 / 12`) so the number stays interpretable
  against the README's existing "0–10" framing, or update the README/docs to
  state the new scale explicitly. Pick one and be consistent everywhere
  (dashboard, notifications, docs).
- **Do not hand-pick `threshold_watch`/`threshold_good`/`threshold_strong` as
  final.** These are placeholders. The real thresholds get set from the Phase
  8 validation report (walk-forward + parameter sweep), not from intuition.
  Leave a `# TODO: recalibrate from validation report` comment on the
  defaults.
- `csd_quality`/`breakout_quality`/`retest_quality` are now required
  parameters instead of the old `has_csd`/`has_breakout`/`has_retest` booleans.
  Update the call site in `app/strategy/csd_strategy.py`
  (`self.scoring.score(confirmation, has_csd=True, has_breakout=True,
  has_retest=True)`) to pass the real graded values from the CSD/breakout/retest
  events instead of hard-coded `True` — this hard-coding is itself a second,
  smaller instance of the same problem your report flagged, worth noting in
  your response.

### B4. Update dependent call sites

- `app/backtest_runner.py` currently reads `assessment.score.setup_valid` and
  `assessment.score.confluence_score` when building `TradeAudit`. Update to
  store `assessment.score.total` and `assessment.score.classification` instead.
  Check `app/backtests.py` for the `TradeAudit` schema and widen the relevant
  column from bool/int to a decimal + string, with a migration if the table is
  already persisted anywhere real.
- `app/notifications/formatting.py` likely renders the old 0–10 point
  breakdown for alerts (per the V1 spec's alert template) — check it and
  update to render the new component dict.
- Search the whole repo for `setup_valid`, `confluence_score`,
  `SignalClassification.CONFIRMATION_PENDING` and update every reference;
  `CONFIRMATION_PENDING` no longer exists as a name — decide whether
  `GOOD_SIGNAL`/`STRONG_SIGNAL` map onto what used to gate risk-analysis
  triggering in `csd_strategy.py` (`if assessment.score.classification is
  SignalClassification.CONFIRMATION_PENDING:`) — this should now presumably
  trigger on `GOOD_SIGNAL` or `STRONG_SIGNAL`.

### B5. Update existing tests

`tests/test_confirmation_scoring.py` and any test in
`tests/test_strategy_engine.py` asserting on `setup_valid`/`confluence_score`
will need rewriting against the new `ConfidenceScore` shape. Do not delete
test coverage — port each existing case to assert equivalent behavior against
the graded score (e.g. "all four indicators supportive" should still land in
the top classification band; "CSD/breakout/retest absent" should still land in
`NO_TRADE`).

---

## Acceptance for this patch

- All three tests in `tests/test_swing_store.py` pass, including the filled-in
  `test_replay_engine_has_no_future_access`.
- `pytest` passes in full — no test silently skipped or weakened to pass.
- `grep -rn "setup_valid\|confluence_score" app/` returns nothing.
- Report which files were touched beyond the ones listed above, and why.
- Do not proceed to the cost model or exit policy in this same patch — stop
  here for review.
