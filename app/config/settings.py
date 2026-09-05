from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
import re
import logging
from typing import Any

import yaml

SUPPORTED_TIMEFRAMES = frozenset({"15m", "1h", "4h"})
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{3,30}$")
LOGGER = logging.getLogger(__name__)


def normalize_symbol(symbol: str) -> str:
    """Return Binance's canonical uppercase symbol or raise ValueError."""
    normalized = symbol.strip().upper().replace("/", "").replace("-", "")
    if not _SYMBOL_RE.fullmatch(normalized):
        raise ValueError(f"Invalid symbol format: {symbol!r}")
    return normalized


@dataclass(frozen=True)
class WebSocketSettings:
    reconnect_enabled: bool = True
    max_reconnect_delay_seconds: int = 60
    receive_timeout_seconds: int = 90


@dataclass(frozen=True)
class SwingSettings:
    left_bars: int = 3
    right_bars: int = 3


@dataclass(frozen=True)
class CSDSettings:
    minimum_close_distance_percent: Decimal = Decimal("0.05")


@dataclass(frozen=True)
class RetestSettings:
    zone_percent: Decimal = Decimal("0.20")
    maximum_bars_after_breakout: int = 12


@dataclass(frozen=True)
class ConfirmationSettings:
    rsi_bullish_minimum: Decimal = Decimal("50")
    rsi_bearish_maximum: Decimal = Decimal("50")
    volume_ratio_minimum: Decimal = Decimal("1")


@dataclass(frozen=True)
class ScoringSettings:
    """Temporary V1 quality normalizers and weights; recalibrate after validation."""
    csd_saturation_percent: Decimal = Decimal("0.8")
    breakout_saturation_percent: Decimal = Decimal("0.8")
    ema_separation_saturation_percent: Decimal = Decimal("0.5")
    macd_histogram_saturation_percent: Decimal = Decimal("0.1")
    csd_weight: Decimal = Decimal("2.0")
    breakout_weight: Decimal = Decimal("2.0")
    retest_weight: Decimal = Decimal("2.0")
    ema_weight: Decimal = Decimal("1.5")
    rsi_weight: Decimal = Decimal("1.0")
    macd_weight: Decimal = Decimal("1.0")
    volume_weight: Decimal = Decimal("1.0")
    htf_weight: Decimal = Decimal("1.5")


@dataclass(frozen=True)
class RiskSettings:
    stop_buffer_percent: Decimal = Decimal("0")


@dataclass(frozen=True)
class CostSettings:
    taker_fee_percent: Decimal = Decimal("0.05")
    maker_fee_percent: Decimal = Decimal("0.02")
    entry_order_type: str = "taker"
    exit_order_type: str = "taker"
    slippage_percent: Decimal = Decimal("0.02")
    slippage_percent_stop: Decimal = Decimal("0.05")
    funding_rate_fixed_percent: Decimal = Decimal("0.01")


@dataclass(frozen=True)
class ExitLeg:
    target_r: Decimal
    size_percent: Decimal


@dataclass(frozen=True)
class ExitPolicySettings:
    name: str = "scaled"
    legs: tuple[ExitLeg, ...] = (
        ExitLeg(Decimal("1.0"), Decimal("50")),
        ExitLeg(Decimal("2.0"), Decimal("25")),
        ExitLeg(Decimal("3.0"), Decimal("25")),
    )
    move_stop_to_breakeven_after_leg: int | None = 1
    breakeven_offset_r: Decimal = Decimal("0.1")
    time_stop_bars: int | None = 48


@dataclass(frozen=True)
class Settings:
    symbols: dict[str, bool]
    invalid_symbols: tuple[str, ...]
    primary_timeframe: str
    confirmation_timeframes: tuple[str, ...]
    historical_candle_limit: int
    database_path: Path
    websocket: WebSocketSettings
    swing: SwingSettings
    csd: CSDSettings
    retest: RetestSettings
    confirmation: ConfirmationSettings
    scoring: ScoringSettings
    risk: RiskSettings
    cost: CostSettings
    exit_policy: ExitPolicySettings

    @property
    def enabled_symbols(self) -> tuple[str, ...]:
        return tuple(symbol for symbol, enabled in self.symbols.items() if enabled)

    @property
    def timeframes(self) -> tuple[str, ...]:
        return (self.primary_timeframe, *self.confirmation_timeframes)


def _require_timeframe(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Unsupported timeframe {value!r}; expected one of {sorted(SUPPORTED_TIMEFRAMES)}")
    return normalized


def load_settings(path: str | Path = "config.yaml") -> Settings:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw: dict[str, Any] = yaml.safe_load(handle) or {}
    raw_symbols = raw.get("symbols", {})
    if not isinstance(raw_symbols, dict):
        raise ValueError("symbols must be a mapping")
    symbols: dict[str, bool] = {}
    invalid_symbols: list[str] = []
    for configured_symbol, options in raw_symbols.items():
        try:
            symbol = normalize_symbol(str(configured_symbol))
        except ValueError:
            LOGGER.error("Ignoring invalid configured symbol: %r", configured_symbol)
            invalid_symbols.append(str(configured_symbol))
            continue
        if not isinstance(options, dict):
            raise ValueError(f"Symbol settings for {symbol} must be a mapping")
        symbols[symbol] = bool(options.get("enabled", False))
    timeframes = raw.get("timeframes", {})
    primary = _require_timeframe(str(timeframes.get("primary", "15m")))
    confirmations = tuple(_require_timeframe(str(item)) for item in timeframes.get("confirmation", ["1h", "4h"]))
    if len(set((primary, *confirmations))) != len((primary, *confirmations)):
        raise ValueError("Timeframes must not contain duplicates")
    data = raw.get("data", {})
    limit = int(data.get("historical_candle_limit", 500))
    if not 1 <= limit <= 1500:
        raise ValueError("historical_candle_limit must be between 1 and 1500")
    websocket = raw.get("websocket", {})
    swing = raw.get("swing", {})
    left_bars, right_bars = int(swing.get("left_bars", 3)), int(swing.get("right_bars", 3))
    if left_bars < 1 or right_bars < 1:
        raise ValueError("swing left_bars and right_bars must be positive")
    csd = raw.get("csd", {})
    minimum_distance = Decimal(str(csd.get("minimum_close_distance_percent", "0.05")))
    if minimum_distance < 0:
        raise ValueError("csd minimum_close_distance_percent cannot be negative")
    retest = raw.get("retest", {})
    retest_zone = Decimal(str(retest.get("zone_percent", "0.20")))
    maximum_bars = int(retest.get("maximum_bars_after_breakout", 12))
    if retest_zone < 0 or maximum_bars < 0:
        raise ValueError("retest zone_percent and maximum_bars_after_breakout cannot be negative")
    confirmation = raw.get("confirmation", {})
    bullish_rsi = Decimal(str(confirmation.get("rsi_bullish_minimum", "50")))
    bearish_rsi = Decimal(str(confirmation.get("rsi_bearish_maximum", "50")))
    volume_ratio = Decimal(str(confirmation.get("volume_ratio_minimum", "1")))
    if not (Decimal(0) <= bullish_rsi <= Decimal(100) and Decimal(0) <= bearish_rsi <= Decimal(100) and volume_ratio >= 0):
        raise ValueError("confirmation RSI thresholds must be 0–100 and volume_ratio_minimum cannot be negative")
    scoring = raw.get("scoring", {})
    scoring_values = {
        name: Decimal(str(scoring.get(name, default)))
        for name, default in {
            "csd_saturation_percent": "0.8", "breakout_saturation_percent": "0.8",
            "ema_separation_saturation_percent": "0.5", "macd_histogram_saturation_percent": "0.1",
            "csd_weight": "2.0", "breakout_weight": "2.0", "retest_weight": "2.0",
            "ema_weight": "1.5", "rsi_weight": "1.0", "macd_weight": "1.0",
            "volume_weight": "1.0", "htf_weight": "1.5",
        }.items()
    }
    if any(value <= 0 for value in scoring_values.values()):
        raise ValueError("scoring saturations and weights must be positive")
    risk = raw.get("risk", {})
    stop_buffer = Decimal(str(risk.get("stop_buffer_percent", "0")))
    if stop_buffer < 0:
        raise ValueError("risk stop_buffer_percent cannot be negative")
    cost = raw.get("cost", {})
    cost_values = {
        name: Decimal(str(cost.get(name, default)))
        for name, default in {
            "taker_fee_percent": "0.05", "maker_fee_percent": "0.02",
            "slippage_percent": "0.02", "slippage_percent_stop": "0.05",
            "funding_rate_fixed_percent": "0.01",
        }.items()
    }
    if any(value < 0 for value in cost_values.values()):
        raise ValueError("cost values cannot be negative")
    entry_order_type = str(cost.get("entry_order_type", "taker")).lower()
    exit_order_type = str(cost.get("exit_order_type", "taker")).lower()
    if entry_order_type not in {"taker", "maker"} or exit_order_type not in {"taker", "maker"}:
        raise ValueError("cost entry_order_type and exit_order_type must be 'taker' or 'maker'")
    exit_policy = raw.get("exit_policy", {})
    policy_name = str(exit_policy.get("name", "scaled"))
    if policy_name not in {"single_target", "scaled"}:
        raise ValueError("exit_policy name must be 'single_target' or 'scaled'")
    raw_legs = exit_policy.get("legs", [
        {"target_r": "1.0", "size_percent": "50"},
        {"target_r": "2.0", "size_percent": "25"},
        {"target_r": "3.0", "size_percent": "25"},
    ])
    if not isinstance(raw_legs, list) or not raw_legs:
        raise ValueError("exit_policy legs must be a non-empty list")
    legs = tuple(ExitLeg(Decimal(str(item["target_r"])), Decimal(str(item["size_percent"]))) for item in raw_legs)
    if any(leg.target_r <= 0 or leg.size_percent <= 0 for leg in legs) or sum(leg.size_percent for leg in legs) != Decimal("100"):
        raise ValueError("exit_policy leg targets and sizes must be positive and sizes must sum to 100")
    move_stop = exit_policy.get("move_stop_to_breakeven_after_leg", 1)
    move_stop = int(move_stop) if move_stop is not None else None
    if move_stop is not None and not 1 <= move_stop <= len(legs):
        raise ValueError("exit_policy move_stop_to_breakeven_after_leg must name an existing leg")
    time_stop = exit_policy.get("time_stop_bars", 48)
    time_stop = int(time_stop) if time_stop is not None else None
    if time_stop is not None and time_stop <= 0:
        raise ValueError("exit_policy time_stop_bars must be positive when set")
    breakeven_offset = Decimal(str(exit_policy.get("breakeven_offset_r", "0.1")))
    return Settings(
        symbols=symbols,
        invalid_symbols=tuple(invalid_symbols),
        primary_timeframe=primary,
        confirmation_timeframes=confirmations,
        historical_candle_limit=limit,
        database_path=Path(data.get("database_path", "data/signal_engine.db")),
        websocket=WebSocketSettings(
            reconnect_enabled=bool(websocket.get("reconnect_enabled", True)),
            max_reconnect_delay_seconds=max(1, int(websocket.get("max_reconnect_delay_seconds", 60))),
            receive_timeout_seconds=max(1, int(websocket.get("receive_timeout_seconds", 90))),
        ),
        swing=SwingSettings(left_bars, right_bars),
        csd=CSDSettings(minimum_distance),
        retest=RetestSettings(retest_zone, maximum_bars),
        confirmation=ConfirmationSettings(bullish_rsi, bearish_rsi, volume_ratio),
        scoring=ScoringSettings(**scoring_values),
        risk=RiskSettings(stop_buffer),
        cost=CostSettings(entry_order_type=entry_order_type, exit_order_type=exit_order_type, **cost_values),
        exit_policy=ExitPolicySettings(policy_name, legs, move_stop, breakeven_offset, time_stop),
    )
