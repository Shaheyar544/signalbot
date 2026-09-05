# V2 Implementation Gap Report

## Summary

`CODEX-IMPLEMENTATION-PROMPT-V2.md` is largely not implemented yet. The
repository has a functional market-data and signal-analysis foundation plus
early diagnostic replay work, but it does not meet V2's research-validation
architecture.

## V2 Comparison

| V2 area | Current status | Remaining work |
| --- | --- | --- |
| Point-in-time pivot gating | Partial | Add `confirmed_time` to swings, private swing storage, `get_swings(as_of)`, and V2 leakage tests. |
| Sequential replay | Partial | Replay is chronological and the strategy uses bounded candle reads, but the full V2 causal acceptance suite is incomplete. |
| Forming-candle indicators | Mostly implemented | Add the required extreme-forming-candle regression test. |
| Historical data | Partial | Add integrity-checked 3-year historical acquisition for five symbols and three timeframes. |
| Cost model | Missing | Add costs module, fee/slippage/funding configuration, and gross/net R accounting. |
| Exit policy | Missing | Add pluggable single-target, scaled, and trailing exit policies. |
| SAME_CANDLE policy | Partial | SL-first resolver and diagnostic integration test exist; standardize persisted method as `SAME_CANDLE`. |
| Scoring | Locked decision conflict | V2 requests graded 0–10 scoring, while the approved project decision is `setup_valid` plus 0–4 confluence. Do not replace the approved model without explicit direction. |
| Strategy variants | Missing | Add entry, HTF, regime, session, and parameter-sweep configuration. |
| Backtest engine | Partial | Diagnostic runner and persistence exist; complete lifecycle, audit, metrics, and reports are missing. |
| Metrics/statistics | Missing | Add CI, expectancy, profit factor, drawdown, streaks, MFE/MAE, and result buckets. |
| Random baseline | Missing | Add reproducible random-entry baseline, percentile, and p-value. |
| Walk-forward validation | Missing | Add rolling in-sample/out-of-sample validation and overfitting ratio. |
| Parameter robustness | Missing | Add sweeps, plots, plateau measurement, and curve-fit warnings. |
| Go-live gate | Missing | Add gate evaluation, validation-report checks, and observation-mode behavior. |
| Live/replay parity | Missing | Add recorded-candle parity fixture and exact signal comparison. |
| Backtest API/dashboard | Missing | Add `/api/backtests`, run details, audit trades, and validation warnings. |
| Backtest CLI | Missing | Add `python -m app.backtest`. |
| Notifications | Already exists, but conflicts with V2 build order | Providers are disabled by default; V2 would defer further notification work until validation review. |
| Documentation | Needs update | README contains obsolete 0–10 / `GOOD_SIGNAL` / `STRONG_SIGNAL` descriptions and lacks V2 research gates. |

## Relevant Existing Components

- Early sequential replay: `app/replay.py`
- Diagnostic backtest runner: `app/backtest_runner.py`
- SL-first intrabar resolver: `app/backtesting.py`
- Backtest persistence models: `app/backtests.py`
- Swing implementation requiring V2 causal redesign: `app/structure/swings.py`
- Existing monitoring dashboard: `app/dashboard.py`

## Recommended Next Step

Implement V2 Section 1 before costs, exits, metrics, or validation reporting:

1. Add `pivot_time` and `confirmed_time` to swing data.
2. Expose only `get_swings(as_of)` for strategy use.
3. Add the three required V2 leakage tests:
   - pivot unavailable before confirmation;
   - replay has no future access;
   - indicators exclude an extreme forming candle.

No profitability conclusion can be drawn from the current implementation.
