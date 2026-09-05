"""Execution-only research scope helpers; never persist or mutate config.yaml."""
from __future__ import annotations

from dataclasses import replace

from app.config.settings import HistoricalDataSettings, Settings


def scoped_research_settings(settings: Settings, symbols: tuple[str, ...]) -> Settings:
    """Return a frozen settings copy whose historical universe is this run only."""
    return replace(settings, historical=replace(settings.historical, symbols=tuple(symbols)))


def validation_scope(symbols: tuple[str, ...], label: str | None) -> str:
    if label:
        return label
    return "OFFICIAL_MULTI_SYMBOL_VALIDATION" if len(symbols) > 1 else "SINGLE_SYMBOL_DIAGNOSTIC"
