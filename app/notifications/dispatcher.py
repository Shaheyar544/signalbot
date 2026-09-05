from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from app.notifications.base import DeliveryResult, NotificationProvider
from app.signals.models import SignalRecord
from app.storage.repositories import NotificationRepository

LOGGER = logging.getLogger(__name__)


class NotificationDispatcher:
    def __init__(self, providers: Sequence[NotificationProvider], repository: NotificationRepository,
                 max_attempts: int = 3, retry_delay_seconds: float = 1) -> None:
        if max_attempts < 1 or retry_delay_seconds < 0:
            raise ValueError("Invalid notification retry configuration")
        self.providers, self.repository = tuple(providers), repository
        self.max_attempts, self.retry_delay_seconds = max_attempts, retry_delay_seconds

    async def dispatch(self, signal: SignalRecord) -> list[DeliveryResult]:
        results: list[DeliveryResult] = []
        for provider in self.providers:
            result = await self._deliver(provider, signal)
            self.repository.save_attempt(signal.signal_id, result)
            results.append(result)
        return results

    async def _deliver(self, provider: NotificationProvider, signal: SignalRecord) -> DeliveryResult:
        last_error: str | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = await provider.send(signal)
                if result.success:
                    return DeliveryResult(provider.name, True, attempts=attempt)
                last_error = result.error or "Provider reported failure"
            except Exception as error:  # Provider failure must be isolated.
                last_error = str(error)
                LOGGER.warning("Notification provider %s failed on attempt %s: %s", provider.name, attempt, error)
            if attempt < self.max_attempts and self.retry_delay_seconds:
                await asyncio.sleep(self.retry_delay_seconds * (2 ** (attempt - 1)))
        return DeliveryResult(provider.name, False, last_error, self.max_attempts)
