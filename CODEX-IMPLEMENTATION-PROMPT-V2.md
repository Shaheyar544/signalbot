# Codex Implementation Prompt V2 — ETH CSD Signal Bot

Act as a senior quantitative developer and production systems engineer.

Implement `ETH-CSD-SIGNAL-BOT-SPEC.md` in this repository, **with the amendments
below taking priority wherever they conflict with the original spec.**

The purpose of this system is not to send alerts. It is to **determine whether
this strategy has a measurable edge, and to refuse to run live until that is
proven.** Alerting is the last feature built, not the first.

---

## 0. Non-negotiable rules

- Signal-only. Never place orders. Never request trading or withdrawal API scopes.
- Never hard-code price levels. All levels derive from detected structure.
- Live mode and replay mode share one strategy engine, one code path, one config.
- Never log secrets. Notification failure must never crash the engine.
- **Every number the strategy sees must be causally available at that moment in
  time.** See Section 1. Violating this invalidates the entire project.

---

## 1. Point-in-time correctness (highest priority)

This is the most important section in the document. Implement it first and test
it hardest.

### 1.1 The pivot confirmation lag problem

With `left_bars=3, right_bars=3`, a swing high at index `i` cannot be known until
bar `i+3` has closed. Any code that scans the full candle array for pivots and
then evaluates a break is using future information.

**Required implementation:**

- `SwingPoint` carries two timestamps: `pivot_time` (where the pivot is) and
  `confirmed_time` (`pivot_time + right_bars` intervals).
- The structure engine exposes `get_swings(as_of: datetime)` which returns **only**
  swings where `confirmed_time <= as_of`.
- No other access path to swing data exists. Make the underlying list private.

### 1.2 Closed-candle discipline

- Indicators are computed on closed candles only. The forming candle is never an
  input to EMA/RSI/MACD/BB/volume.
- CSD, breakout, and retest evaluation runs on candle close events only.
- In replay, feed candles one at a time through the identical event handler used
  by the WebSocket path. The replay loop must not have access to `candles[i+1:]`.

### 1.3 Required leakage tests

Write these tests. They are acceptance-blocking:

- `test_swing_not_visible_before_confirmation` — a pivot at `i` must be absent
  from `get_swings(as_of=t_i)` and present at `get_swings(as_of=t_{i+3})`.
- `test_replay_engine_has_no_future_access` — run replay on a candle series, then
  run it again with all candles after the signal bar deleted. The signal must be
  byte-identical.
- `test_indicator_excludes_forming_candle` — append a forming candle with an
  extreme value; all indicator outputs must be unchanged.

---

## 2. Cost model (blocking — build before the strategy)

Create `app/backtest/costs.py`. No performance number may ever be reported gross.

```yaml
costs:
  taker_fee_percent: 0.05      # per side; verify against current Binance USD-M schedule
  maker_fee_percent: 0.02
  entry_order_type: taker      # retest entries realistically fill as taker
  exit_order_type: taker
  slippage_percent: 0.02       # per side
  slippage_percent_stop: 0.05  # stops slip worse; model separately
  funding_rate_source: historical   # historical | fixed | none
  funding_rate_fixed_percent: 0.01  # per 8h if fixed
```

Requirements:

- Every trade record stores `gross_r`, `total_cost_r`, and `net_r`.
- Funding is charged for each 8h boundary crossed while a position is open.
- Stop-loss exits use `slippage_percent_stop`, not the normal slippage figure.
- The reporting layer prints net results. Gross may appear only as a secondary
  diagnostic column, explicitly labelled.

---

## 3. Exit policy (currently undefined — must be specified)

The original spec lists TP1/TP2/TP3/TP4 but never says how a position is managed.
Implement exits as a configurable, pluggable policy so different policies can be
compared on identical signals.

```yaml
exit_policy:
  name: scaled          # options: single_target | scaled | trailing
  legs:
    - target_r: 1.0
      size_percent: 50
    - target_r: 2.0
      size_percent: 25
    - target_r: 3.0
      size_percent: 25
  move_stop_to_breakeven_after_leg: 1   # null to disable
  breakeven_offset_r: 0.1              # cover costs, not just entry price
  time_stop_bars: 48                    # force exit after N 15M bars; null to disable
  intrabar_fill_assumption: pessimistic  # if a bar spans both SL and TP, assume SL
```

`intrabar_fill_assumption: pessimistic` is mandatory for replay. When a single
candle's range contains both the stop and a target, the backtest must assume the
stop filled first. Optimistic assumptions here are the second-largest source of
inflated backtest results after look-ahead bias.

Implement at least `single_target` (TP2 only, all-in/all-out) and `scaled` so the
comparison can be run.

---

## 4. Rebuild the confidence score

The original score is degenerate: CSD+Breakout+Retest = 6 points are all mandatory
preconditions, so every evaluated signal scores 6–10, and the ≥7 threshold only
rejects setups where all four optional indicators fail. The 0–4 and 5–6 bands are
unreachable.

Replace binary points with **graded quality scores**. Each component returns a
float in `[0, 1]`; the weighted sum is the confidence.

```yaml
scoring:
  weights:
    csd_quality: 2.0
    breakout_quality: 2.0
    retest_quality: 2.0
    trend_alignment: 1.5
    momentum: 1.0
    volume: 1.0
    htf_agreement: 1.5
  threshold_watch: 5.0
  threshold_signal: 7.0
```

Grading rules:

- `csd_quality` — normalized break distance beyond the swing, measured in ATR,
  clipped to `[0,1]`. A 0.1-ATR break scores near 0; a 0.8-ATR break scores 1.
- `breakout_quality` — closing range position of the breakout candle
  (`(close - low) / (high - low)` for longs), combined with volume ratio.
- `retest_quality` — how cleanly price rejected: wick length into the zone versus
  close position on rejection. A deep close-through that recovered scores lower
  than a clean wick rejection.
- `trend_alignment` — EMA10/50/200 ordering and price position, graded not binary.
- `momentum` — RSI distance from 50 and MACD histogram slope, normalized.
- `htf_agreement` — replaces the undefined "1H not strongly bearish." Define
  quantitatively: 1H and 4H each classified `bullish | neutral | bearish` by
  `close vs EMA50` plus most recent 1H/4H structure event. Score 1.0 when both
  agree with the trade direction, 0.5 for neutral, 0.0 for opposed.

Log the full component vector on every signal. Threshold tuning happens later,
from data — do not treat 7.0 as final.

---

## 5. Strategy variants to instrument (do not pre-decide)

Build these as config flags so replay can measure each. Do not assume the
original spec's choices are correct.

```yaml
variants:
  entry_mode: retest        # retest | immediate | both
  require_htf_agreement: false
  regime_filter: none       # none | atr_percentile | ema_slope | adx
  regime_min_atr_percentile: 40
  session_filter: none      # none | us | eu | asia | us_eu
```

Rationale you must preserve in the code comments:

- **`entry_mode: immediate`** matters because requiring a retest structurally
  excludes the strongest momentum breakouts (which never come back) while
  retaining the weak ones (which come back because they failed). This selection
  bias may be the dominant effect in the whole strategy. Measure both branches on
  the same detected breakouts.
- **`regime_filter`** matters because breakout-retest is a trend-continuation
  pattern and ETH on 15M spends most of its time mean-reverting. Report results
  bucketed by regime regardless of whether the filter is enabled.
- `max_bars_after_breakout: 12` (3 hours) is an untested guess. Sweep it.

---

## 6. Backtest and statistics engine (build before notifications)

Create `app/backtest/` with `engine.py`, `metrics.py`, `walkforward.py`,
`report.py`. This is the core deliverable, not a script in `/scripts`.

### 6.1 Required metrics

Per run, net of costs: trade count, win rate with Wilson 95% confidence interval,
expectancy in R, total R, profit factor, max drawdown in R, longest losing streak,
average bars in trade, MFE/MAE distributions, and results bucketed by confidence
band, direction, regime, session, and month.

### 6.2 Baseline comparison (mandatory)

Compute a random-entry baseline: same trade count, same holding period
distribution, same exit policy, entries at uniformly random closed candles. Run
1,000 iterations. Report where the strategy's expectancy falls in that
distribution as a percentile and p-value.

**A strategy that does not clear its random baseline at p < 0.05 has no
demonstrated edge, regardless of how good the equity curve looks.**

### 6.3 Sample size

ETH 15M will produce roughly 10–25 valid setups per month. That is far too few
for statistical confidence within a year of data.

Therefore: **run replay across ETHUSDT, BTCUSDT, SOLUSDT, BNBUSDT, and XRPUSDT**
even though V1 only alerts on ETH. This is for sample size, not for trading. If
the edge exists only on ETH and vanishes on four correlated majors, it is noise.

Fetch and cache at least 3 years of 15M/1H/4H klines per symbol via REST.

### 6.4 Walk-forward validation

Never report in-sample optimized results.

- Split history into rolling windows: 6 months in-sample, 2 months out-of-sample,
  stepping forward 2 months.
- Optimize parameters on in-sample only; evaluate on the untouched out-of-sample.
- Report the aggregate out-of-sample curve. That is the only number that counts.
- Report the in-sample / out-of-sample expectancy ratio. A ratio above roughly 2.0
  indicates overfitting.

### 6.5 Parameter robustness

For each key parameter (`left_bars`, `right_bars`,
`minimum_close_distance_percent`, `retest.zone_percent`,
`maximum_bars_after_breakout`, `stop_buffer_atr`, `threshold_signal`), sweep a
range and plot expectancy against the value.

A parameter with a sharp isolated peak is curve-fit. Only broad plateaus are
tradeable. Report the plateau width for each.

---

## 7. Go-live gate (enforce in code)

Add `app/backtest/gate.py`. The application refuses to enter live alerting mode
unless a validation report exists and passes:

```yaml
go_live_gate:
  min_out_of_sample_trades: 100
  min_net_expectancy_r: 0.10
  max_in_sample_out_sample_ratio: 2.0
  min_baseline_percentile: 95
  max_drawdown_r: 20
  require_positive_in_symbols: 3   # of the 5 tested
  report_max_age_days: 30
```

On startup in live mode, load the report, evaluate the gate, and if it fails,
log the failing criteria and start in **observation mode**: full evaluation and
database logging, notifications suppressed. Allow `--force-live` only with an
explicit acknowledgement flag, and log that it was used.

---

## 8. Revised build order

The original ordering builds four notification providers before knowing whether
the strategy works. Reverse it.

| Phase | Work | Gate |
|---|---|---|
| 1 | Repo inspection, plan, typed domain models | Plan stated |
| 2 | Historical data fetcher + cache, 5 symbols, 3 years, 15M/1H/4H | Data integrity tests pass |
| 3 | Indicators, unit-tested against known fixtures | Tests pass |
| 4 | Swing/structure engine **with `as_of` gating** | Section 1.3 leakage tests pass |
| 5 | CSD, breakout, retest engines | Wick-rejection tests pass |
| 6 | Cost model + exit policy engine | Cost math unit-tested |
| 7 | Backtest engine, metrics, random baseline | Baseline reproducible |
| 8 | **Full validation run + walk-forward + sensitivity sweeps** | **Report produced** |
| 9 | **STOP. Present the report before continuing.** | Human review |
| 10 | Graded scoring, threshold selection from Phase 8 data | Re-validated |
| 11 | State machine, signal manager, duplicate prevention | Tests pass |
| 12 | SQLite persistence, migrations, repositories | Restart test passes |
| 13 | Live WebSocket path sharing the Phase 4–7 engine | Reconnect/reconcile tests pass |
| 14 | Go-live gate | Refuses when report fails |
| 15 | Notification adapters (Discord first, others after) | Isolation test passes |
| 16 | Docker, health checks, security audit | Audit clean |

**Phase 9 is a hard stop.** Do not build notifications until the validation report
has been reviewed. If the strategy shows no edge, the correct outcome is to report
that and stop — not to build the remaining 60% of the system anyway.

---

## 9. Live/replay parity

Add `test_live_replay_parity`: record 7 days of live WebSocket candles to disk,
then replay the same file offline. Signals must match exactly on ID, entry, stop,
targets, and confidence to the last decimal. Any divergence is a bug in one of
the two paths and blocks release.

---

## 10. Required output

Return, in this order:

1. Implementation plan and phase status
2. **The full validation report from Phase 8**, net of costs, out-of-sample:
   trade counts, expectancy, win rate with CI, profit factor, max drawdown,
   baseline percentile and p-value, per-symbol breakdown, per-regime breakdown,
   parameter sensitivity plateaus, in-sample/out-of-sample ratio
3. Files created and modified
4. Test results, with leakage tests called out explicitly
5. Whether the go-live gate passes, and which criteria fail if not
6. Known limitations and sources of remaining bias
7. Required environment variables and run commands

Do not report any performance figure without costs applied. Do not describe the
system as working based on in-sample results. Do not implement auto-trading.
