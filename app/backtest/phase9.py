"""Phase 9 validation orchestration over the frozen strategy and trade engine."""
from __future__ import annotations

from dataclasses import dataclass, asdict, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Sequence
from bisect import bisect_right

from app.backtest.costs import CostModel
from app.backtest.exits import ExitPolicyEngine, TradeState, gross_r
from app.backtest.metrics import calculate_metrics
from app.backtests import TradeAudit
from app.config.settings import Settings
from app.data.candles import CandleStore
from app.events.models import Candle, CandleClosedEvent
from app.strategy.csd_strategy import CSDStrategyEngine, SetupAssessment
from app.strategy.regime import RegimeClassifier
from app.strategy.risk import RiskAnalysis
from app.backtest.walkforward import WalkForwardWindow, rolling_windows


@dataclass(frozen=True)
class StrategyPlan:
    analysis: RiskAnalysis
    assessment: SetupAssessment
    signal_candle: Candle


@dataclass(frozen=True)
class RandomEntryCandidate:
    """A uniformly sampled closed candle with a frozen risk template.

    The candle timestamp is randomized; the direction and risk geometry are
    drawn cyclically from observed plans so the null keeps the strategy's
    empirical risk/side distribution without reusing realized returns.
    """
    plan: StrategyPlan


@dataclass(frozen=True)
class RandomEntryResult:
    iterations: int
    trade_count: int
    expectancies_r: tuple[Decimal, ...]
    observed_expectancy_r: Decimal
    percentile: Decimal
    p_value: Decimal


@dataclass(frozen=True)
class WalkForwardResult:
    windows: tuple[dict[str, Any], ...]
    oos_trade_count: int
    oos_total_r: Decimal
    oos_expectancy_r: Decimal


@dataclass(frozen=True)
class SensitivityPoint:
    parameter: str
    value: Decimal
    expectancy_r: Decimal


@dataclass(frozen=True)
class SensitivityResult:
    points: tuple[SensitivityPoint, ...]
    plateau_width: int
    selected_value: Decimal | None = None
    unsupported_parameters: tuple[str, ...] = ()


def run_random_entry_experiment(candidates: Sequence[Any], simulate_trade: Callable[[Any], Decimal | TradeAudit],
                                *, trade_count: int, iterations: int = 1000, seed: int = 7,
                                observed_expectancy: Decimal = Decimal(0)) -> RandomEntryResult:
    """Sample eligible entry events and run the canonical simulator for each sample."""
    import random
    if not candidates or not 1 <= trade_count <= len(candidates):
        raise ValueError("trade_count must be within the eligible candidate count")
    rng = random.Random(seed)
    expectancies: list[Decimal] = []
    for _ in range(iterations):
        values: list[Decimal] = []
        for candidate in rng.sample(list(candidates), trade_count):
            result = simulate_trade(candidate)
            if result is None:
                values.append(Decimal(0))
            else:
                values.append(result.net_r if isinstance(result, TradeAudit) else Decimal(result))
        expectancies.append(sum(values, Decimal(0)) / Decimal(len(values)))
    at_or_above = sum(value >= observed_expectancy for value in expectancies)
    percentile = Decimal(sum(value <= observed_expectancy for value in expectancies)) * Decimal(100) / Decimal(iterations)
    return RandomEntryResult(iterations, trade_count, tuple(expectancies), observed_expectancy,
                             percentile, Decimal(at_or_above) / Decimal(iterations))


def execute_walk_forward(windows: Sequence[WalkForwardWindow], replay: Callable[[WalkForwardWindow], tuple[Sequence[Any], Sequence[Any]]]) -> WalkForwardResult:
    """Execute every calendar window through the supplied canonical replay seam."""
    records = []
    oos_values: list[Decimal] = []
    for window in windows:
        in_sample, out_sample = replay(window)
        values = [item.net_r if isinstance(item, TradeAudit) else Decimal(item) for item in out_sample]
        oos_values.extend(values)
        records.append({"in_sample_start": window.in_sample_start.isoformat(),
                        "in_sample_end": window.in_sample_end.isoformat(),
                        "out_sample_start": window.out_sample_start.isoformat(),
                        "out_sample_end": window.out_sample_end.isoformat(),
                        "in_sample_trades": len(in_sample), "out_sample_trades": len(out_sample),
                        "out_sample_total_r": sum(values, Decimal(0))})
    return WalkForwardResult(tuple(records), len(oos_values), sum(oos_values, Decimal(0)),
                             sum(oos_values, Decimal(0)) / Decimal(len(oos_values)) if oos_values else Decimal(0))


def run_sensitivity_sweep(dimensions: dict[str, Sequence[Any]], evaluate: Callable[[str, Any], Decimal]) -> SensitivityResult:
    points = []
    for parameter, values in dimensions.items():
        for value in values:
            points.append(SensitivityPoint(parameter, Decimal(str(value)), evaluate(parameter, value)))
    if not points:
        return SensitivityResult((), 0, None)
    by_parameter: dict[str, list[SensitivityPoint]] = {}
    for point in points:
        by_parameter.setdefault(point.parameter, []).append(point)
    plateau = 0
    for group in by_parameter.values():
        best = max(point.expectancy_r for point in group)
        plateau = max(plateau, sum(abs(point.expectancy_r - best) <= Decimal("0.05") for point in group))
    return SensitivityResult(tuple(points), plateau, None)


async def collect_strategy_plans(settings: Settings, candles: Sequence[Candle]) -> tuple[tuple[Candle, ...], tuple[StrategyPlan, ...]]:
    """Run the frozen strategy once and retain its causal risk plans as eligible events."""
    ordered = tuple(sorted((candle for candle in candles if candle.is_closed), key=lambda candle: candle.open_time))
    store = CandleStore()
    assessments: dict[tuple[str, str], SetupAssessment] = {}
    plans: list[StrategyPlan] = []
    current: Candle | None = None

    def capture_assessment(assessment: SetupAssessment) -> None:
        assessments[(assessment.retest.symbol, assessment.retest.timeframe)] = assessment

    async def capture_analysis(analysis: RiskAnalysis) -> None:
        assert current is not None
        assessment = assessments.get((analysis.symbol, analysis.timeframe))
        if assessment is not None:
            plans.append(StrategyPlan(analysis, assessment, current))

    strategy = CSDStrategyEngine(
        store, settings.primary_timeframe, left_bars=settings.swing.left_bars, right_bars=settings.swing.right_bars,
        minimum_close_distance_percent=settings.csd.minimum_close_distance_percent,
        breakout_method=settings.breakout.method, minimum_close_atr=settings.breakout.minimum_close_atr,
        regime_classifier=RegimeClassifier(**settings.regime.__dict__),
        retest_zone_percent=settings.retest.zone_percent,
        maximum_bars_after_breakout=settings.retest.maximum_bars_after_breakout,
        volume_ratio_minimum=settings.confirmation.volume_ratio_minimum,
        rsi_bullish_minimum=settings.confirmation.rsi_bullish_minimum,
        rsi_bearish_maximum=settings.confirmation.rsi_bearish_maximum,
        stop_buffer_percent=settings.risk.stop_buffer_percent, scoring_settings=settings.scoring,
        on_assessment=capture_assessment, on_risk_analysis=capture_analysis,
    )
    for candle in ordered:
        current = candle
        store.add_candle(candle)
        await strategy.on_candle_closed(CandleClosedEvent(candle.symbol, candle.timeframe, candle))
    return ordered, tuple(plans)


class CanonicalTradeSimulator:
    """Uses the same exit and cost engines as HistoricalBacktestRunner."""
    def __init__(self, settings: Settings, candles: Sequence[Candle] | None = None) -> None:
        self.exit_policy = settings.exit_policy
        self.cost_model = CostModel(settings.cost)
        self._candles_by_key: dict[tuple[str, str], tuple[Candle, ...]] = {}
        self._times_by_key: dict[tuple[str, str], tuple[datetime, ...]] = {}
        if candles is not None:
            self.prepare(candles)

    def prepare(self, candles: Sequence[Candle]) -> None:
        grouped: dict[tuple[str, str], list[Candle]] = {}
        for candle in candles:
            if candle.is_closed:
                grouped.setdefault((candle.symbol, candle.timeframe), []).append(candle)
        self._candles_by_key = {key: tuple(sorted(values, key=lambda item: item.open_time))
                                for key, values in grouped.items()}
        self._times_by_key = {key: tuple(item.open_time for item in values)
                              for key, values in self._candles_by_key.items()}

    def simulate(self, plan: StrategyPlan, candles: Sequence[Candle], trade_id: str = "validation") -> TradeAudit | None:
        trade = ExitPolicyEngine(self.exit_policy).open_trade(
            direction=plan.analysis.direction, entry_low=plan.analysis.entry_low,
            entry_high=plan.analysis.entry_high, reference_entry=plan.analysis.reference_entry,
            stop_loss=plan.analysis.stop_loss)
        series = self._candles_by_key.get((plan.analysis.symbol, plan.analysis.timeframe))
        if series is None:
            series = tuple(c for c in candles if (c.symbol, c.timeframe) ==
                           (plan.analysis.symbol, plan.analysis.timeframe) and c.is_closed)
            series = tuple(sorted(series, key=lambda item: item.open_time))
        start = bisect_right(self._times_by_key.get((plan.analysis.symbol, plan.analysis.timeframe),
                                                     tuple(c.open_time for c in series)),
                             plan.signal_candle.open_time)
        relevant = series[start:]
        if not relevant:
            return None
        engine = ExitPolicyEngine(self.exit_policy)
        for candle in relevant:
            engine.advance(trade, candle)
            if trade.state is TradeState.CLOSED:
                break
            if trade.state is TradeState.EXPIRED_UNFILLED:
                return None
        if trade.state is TradeState.OPEN:
            engine.close_at_end_of_data(trade, relevant[-1])
        if trade.state is not TradeState.CLOSED or trade.entry_fill_price is None or trade.exit_price is None or trade.entered_at is None or trade.closed_at is None:
            return None
        costs = self.cost_model.breakdown(direction=trade.direction, entry=trade.entry_fill_price,
                                          stop_loss=trade.initial_stop_loss, exit_price=trade.exit_price,
                                          is_stop_exit=trade.exit_reason == "SL", opened_at=trade.entered_at,
                                          closed_at=trade.closed_at)
        gross = gross_r(trade)
        targets = plan.analysis.take_profits
        return TradeAudit(trade_id, "validation", plan.signal_candle.close_time, str(trade.direction),
                          trade.entry_fill_price, trade.initial_stop_loss, targets[0], targets[1], targets[2],
                          plan.assessment.score.total, str(plan.assessment.score.classification), trade.closed_at,
                          trade.exit_reason, gross, costs.total_r, gross - costs.total_r, trade.resolution_method,
                          trade.ambiguous_intrabar_events > 0, trade.bars_since_entry, trade.mfe_r, trade.mae_r,
                          plan.analysis.symbol, plan.analysis.regime, None, trade.entered_at, trade.exit_price,
                          plan.assessment.confirmation.one_hour, plan.assessment.confirmation.four_hour,
                          plan.assessment.confirmation.ema, plan.assessment.confirmation.rsi,
                          plan.assessment.confirmation.macd, plan.assessment.confirmation.volume, True, True, True)


class Phase9ValidationOrchestrator:
    """Runs the frozen strategy through baseline, OOS windows, and sensitivity seams."""
    def __init__(self, settings: Settings, *, baseline_iterations: int = 1000) -> None:
        self.settings = settings
        self.baseline_iterations = baseline_iterations

    async def run(self, candles_by_symbol: dict[str, Sequence[Candle]], *, sensitivity_dimensions: dict[str, Sequence[Any]] | None = None,
                  sensitivity_evaluator: Callable[[str, Any], Decimal] | None = None) -> dict[str, Any]:
        per_symbol: dict[str, Any] = {}
        all_audits: list[TradeAudit] = []
        for symbol, candles in candles_by_symbol.items():
            result = await build_symbol_validation(self.settings, candles, baseline_iterations=self.baseline_iterations)
            per_symbol[symbol] = result
            all_audits.extend(result["audits"])
        ordered_times = [candle.open_time for candles in candles_by_symbol.values() for candle in candles]
        windows = rolling_windows(min(ordered_times), max(ordered_times)) if ordered_times else ()
        walkforward = await self._walk_forward(candles_by_symbol, windows)
        sensitivity = None
        if sensitivity_dimensions is not None:
            if sensitivity_evaluator is not None:
                sensitivity = run_sensitivity_sweep(sensitivity_dimensions, sensitivity_evaluator)
            else:
                sensitivity = await self._sensitivity(candles_by_symbol, sensitivity_dimensions)
        metrics = calculate_metrics(all_audits)
        complete = bool(windows and sensitivity is not None and not sensitivity.unsupported_parameters and
                        all(item["baseline"] is not None for item in per_symbol.values()))
        return {
            "status": "READY_FOR_HUMAN_REVIEW" if complete else "INCOMPLETE_VALIDATION_ORCHESTRATION",
            "methodology": {"baseline_iterations": self.baseline_iterations, "same_canonical_exit_cost_engine": True,
                            "random_entry_sampling": "uniformly sampled closed primary-timeframe candles; empirical direction/risk templates",
                            "walk_forward": "6 calendar months IS / 2 calendar months OOS / 2 calendar months step",
                            "parameters_selected": False},
            "metrics": asdict(metrics), "symbols": {key: {"metrics": asdict(value["metrics"]),
                                                              "baseline": asdict(value["baseline"]) if value["baseline"] else None,
                                                              "trade_count": len(value["audits"])} for key, value in per_symbol.items()},
            "walk_forward": asdict(walkforward),
            "sensitivity": asdict(sensitivity) if sensitivity else {"status": "INCOMPLETE_SENSITIVITY_CONFIGURATION"},
        }

    async def _sensitivity(self, candles_by_symbol: dict[str, Sequence[Candle]], dimensions: dict[str, Sequence[Any]]) -> SensitivityResult | None:
        points: list[SensitivityPoint] = []
        unsupported: list[str] = []
        for parameter, values in dimensions.items():
            try:
                tuned_settings = [_replace_frozen_setting(self.settings, parameter, value) for value in values]
            except ValueError:
                unsupported.append(parameter)
                continue
            for value, tuned in zip(values, tuned_settings):
                audits = []
                for candles in candles_by_symbol.values():
                    result = await build_symbol_validation(tuned, candles, baseline_iterations=1)
                    audits.extend(result["audits"])
                metrics = calculate_metrics(audits)
                points.append(SensitivityPoint(parameter, Decimal(str(value)), metrics.expectancy_r))
        if not points:
            return SensitivityResult((), 0, None, tuple(unsupported))
        by_parameter: dict[str, list[SensitivityPoint]] = {}
        for point in points:
            by_parameter.setdefault(point.parameter, []).append(point)
        plateau = max(sum(abs(point.expectancy_r - max(item.expectancy_r for item in group)) <= Decimal("0.05") for point in group)
                       for group in by_parameter.values())
        return SensitivityResult(tuple(points), plateau, None, tuple(unsupported))

    async def _walk_forward(self, candles_by_symbol: dict[str, Sequence[Candle]], windows: Sequence[WalkForwardWindow]) -> WalkForwardResult:
        records = []
        oos_audits: list[TradeAudit] = []
        for window in windows:
            in_count = out_count = 0
            for candles in candles_by_symbol.values():
                window_candles = [candle for candle in candles if window.in_sample_start <= candle.open_time < window.out_sample_end]
                if not window_candles:
                    continue
                result = await build_symbol_validation(self.settings, window_candles, baseline_iterations=1)
                for audit in result["audits"]:
                    if window.out_sample_start <= audit.signal_time < window.out_sample_end:
                        oos_audits.append(audit); out_count += 1
                    elif window.in_sample_start <= audit.signal_time < window.in_sample_end:
                        in_count += 1
            values = [audit.net_r for audit in oos_audits if window.out_sample_start <= audit.signal_time < window.out_sample_end and audit.net_r is not None]
            records.append({"in_sample_trades": in_count, "out_sample_trades": out_count,
                            "out_sample_total_r": sum(values, Decimal(0)),
                            "in_sample_start": window.in_sample_start.isoformat(), "in_sample_end": window.in_sample_end.isoformat(),
                            "out_sample_start": window.out_sample_start.isoformat(), "out_sample_end": window.out_sample_end.isoformat()})
        values = [audit.net_r for audit in oos_audits if audit.net_r is not None]
        return WalkForwardResult(tuple(records), len(values), sum(values, Decimal(0)),
                                 sum(values, Decimal(0)) / Decimal(len(values)) if values else Decimal(0))


def _replace_frozen_setting(settings: Settings, parameter: str, value: Any) -> Settings:
    if parameter == "left_bars":
        return replace(settings, swing=replace(settings.swing, left_bars=int(value)))
    if parameter == "right_bars":
        return replace(settings, swing=replace(settings.swing, right_bars=int(value)))
    if parameter == "minimum_close_distance_percent":
        return replace(settings, csd=replace(settings.csd, minimum_close_distance_percent=Decimal(str(value))))
    if parameter == "retest.zone_percent":
        return replace(settings, retest=replace(settings.retest, zone_percent=Decimal(str(value))))
    if parameter == "maximum_bars_after_breakout":
        return replace(settings, retest=replace(settings.retest, maximum_bars_after_breakout=int(value)))
    raise ValueError(f"Sensitivity dimension {parameter!r} has no frozen-settings mapping")


async def build_symbol_validation(settings: Settings, candles: Sequence[Candle], *, baseline_iterations: int = 1000) -> dict[str, Any]:
    ordered, plans = await collect_strategy_plans(settings, candles)
    simulator = CanonicalTradeSimulator(settings, ordered)
    candidate_results = {id(plan): simulator.simulate(plan, ordered, f"strategy-{index}") for index, plan in enumerate(plans)}
    audits = [audit for audit in candidate_results.values() if audit is not None]
    metrics = calculate_metrics(audits)
    random_candidates = _build_random_entry_candidates(settings, ordered, plans)
    random_results: dict[int, TradeAudit | None] = {}

    def simulate_random(candidate: RandomEntryCandidate) -> TradeAudit | None:
        key = id(candidate)
        if key not in random_results:
            random_results[key] = simulator.simulate(candidate.plan, ordered, "random-entry")
        return random_results[key]

    baseline = run_random_entry_experiment(
        random_candidates,
        simulate_random,
        trade_count=min(len(audits), len(random_candidates)), iterations=baseline_iterations,
        observed_expectancy=metrics.expectancy_r,
    ) if audits and random_candidates else None
    return {"metrics": metrics, "plans": plans, "audits": audits, "baseline": baseline,
            "random_entry_candidates": random_candidates}


def _build_random_entry_candidates(settings: Settings, candles: Sequence[Candle],
                                   plans: Sequence[StrategyPlan]) -> tuple[RandomEntryCandidate, ...]:
    """Create random-entry events from every closed primary-timeframe candle.

    Risk geometry is translated around the sampled candle's close rather than
    copying an observed trade's prices. This prevents the baseline from being
    a permutation of realized returns while keeping direction and risk shape
    controlled and reproducible.
    """
    if not plans:
        return ()
    primary = tuple(sorted((c for c in candles if c.is_closed and c.timeframe == settings.primary_timeframe),
                           key=lambda c: c.open_time))
    template_plans = tuple(plans)
    result: list[RandomEntryCandidate] = []
    for index, candle in enumerate(primary):
        template = template_plans[index % len(template_plans)]
        analysis = template.analysis
        reference = candle.close
        low_offset = analysis.reference_entry - analysis.entry_low
        high_offset = analysis.entry_high - analysis.reference_entry
        risk = analysis.risk_unit
        if analysis.direction.value == "BULLISH":
            stop = reference - risk
            targets = tuple(reference + risk * multiple for multiple in (Decimal(1), Decimal(2), Decimal(3)))
        else:
            stop = reference + risk
            targets = tuple(reference - risk * multiple for multiple in (Decimal(1), Decimal(2), Decimal(3)))
        translated = replace(analysis, symbol=candle.symbol, timeframe=candle.timeframe,
                             entry_low=reference - low_offset, entry_high=reference + high_offset,
                             reference_entry=reference, stop_loss=stop, risk_unit=risk,
                             take_profits=targets, take_profit_4=None)
        result.append(RandomEntryCandidate(replace(template, analysis=translated, signal_candle=candle)))
    return tuple(result)
