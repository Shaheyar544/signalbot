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
class RiskSettings:
    stop_buffer_percent: Decimal = Decimal("0")


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
    risk: RiskSettings

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
    risk = raw.get("risk", {})
    stop_buffer = Decimal(str(risk.get("stop_buffer_percent", "0")))
    if stop_buffer < 0:
        raise ValueError("risk stop_buffer_percent cannot be negative")
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
        risk=RiskSettings(stop_buffer),
    )
