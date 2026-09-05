"""Compare recorded live and offline signal payloads exactly."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence


def canonical_signals(signals: Sequence[dict]) -> str:
    return json.dumps(list(signals), sort_keys=True, separators=(",", ":"), default=str)


def assert_signal_parity(live: Sequence[dict], replay: Sequence[dict]) -> None:
    if canonical_signals(live) != canonical_signals(replay):
        raise AssertionError("live/replay signal parity mismatch")


def load_recording(path: str | Path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
