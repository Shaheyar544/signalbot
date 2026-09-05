"""Exact-identity in-memory cache for immutable research replay results."""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Any, Callable
from collections.abc import Awaitable


def replay_cache_key(*, git_commit: str, strategy_version: str, configuration_hash: str,
                     symbol: str, timeframes: tuple[str, ...], start: str | None,
                     end: str | None, variant: str, parameters: dict[str, Any] | None = None) -> str:
    identity = {"git_commit": git_commit, "strategy_version": strategy_version,
                "configuration_hash": configuration_hash, "symbol": symbol,
                "timeframes": list(timeframes), "start": start, "end": end,
                "variant": variant, "parameters": parameters or {}}
    return sha256(json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


class ResearchReplayCache:
    """Caches only exactly matching immutable replay inputs for one research run."""
    def __init__(self) -> None:
        self._values: dict[str, Any] = {}
        self._hits = 0
        self._misses = 0

    @property
    def stats(self) -> dict[str, int]:
        return {"hits": self._hits, "misses": self._misses}

    def get_or_compute(self, key: str, compute: Callable[[], Any]) -> Any:
        if key in self._values:
            self._hits += 1
            return self._values[key]
        self._misses += 1
        value = compute()
        self._values[key] = value
        return value

    async def get_or_compute_async(self, key: str, compute: Callable[[], Awaitable[Any]]) -> Any:
        if key in self._values:
            self._hits += 1
            return self._values[key]
        self._misses += 1
        value = await compute()
        self._values[key] = value
        return value
