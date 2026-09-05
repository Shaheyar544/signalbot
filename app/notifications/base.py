from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.signals.models import SignalRecord


@dataclass(frozen=True)
class DeliveryResult:
    provider: str
    success: bool
    error: str | None = None
    attempts: int = 1


class NotificationProvider(Protocol):
    name: str

    async def send(self, signal: SignalRecord) -> DeliveryResult: ...
