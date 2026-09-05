from __future__ import annotations
from datetime import datetime
from typing import Sequence
from app.structure.swings import SwingPoint

class SwingStore:
    """The sanctioned swing read path; only confirmed swings are visible."""
    def __init__(self) -> None: self._swings: list[SwingPoint] = []
    def replace(self, swings: Sequence[SwingPoint]) -> None: self._swings = list(swings)
    def get_swings(self, as_of: datetime) -> list[SwingPoint]:
        return [swing for swing in self._swings if swing.confirmed_time is not None and swing.confirmed_time <= as_of]
