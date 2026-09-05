from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.notifications.base import DeliveryResult
from app.signals.models import SignalRecord


class PushProvider:
    """Provider boundary for a configured push service (for example FCM)."""
    name = "push"

    def __init__(self, sender: Callable[[SignalRecord], Awaitable[None]]) -> None:
        self.sender = sender

    async def send(self, signal: SignalRecord) -> DeliveryResult:
        try:
            await self.sender(signal)
            return DeliveryResult(self.name, True)
        except Exception as error:
            return DeliveryResult(self.name, False, str(error))
