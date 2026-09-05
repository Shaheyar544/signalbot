from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.notifications.base import DeliveryResult
from app.notifications.dispatcher import NotificationDispatcher
from app.signals.models import SignalRecord
from app.storage.database import Database
from app.storage.repositories import NotificationRepository
from app.strategy.scoring import SignalClassification
from app.structure.csd import CSDDirection


class SuccessfulProvider:
    name = "success"

    async def send(self, signal):
        return DeliveryResult(self.name, True)


class FailingProvider:
    name = "failure"

    async def send(self, signal):
        raise RuntimeError("delivery unavailable")


def _record():
    return SignalRecord("ETHUSDT-15m-BULLISH-test-100", "ETHUSDT", "15m", CSDDirection.BULLISH,
                           SignalClassification.STRONG_SIGNAL, Decimal("8"), Decimal("99"), Decimal("101"), Decimal("100"),
                        Decimal("98"), Decimal("102"), Decimal("104"), Decimal("106"), None, datetime.now(timezone.utc))


@pytest.mark.asyncio
async def test_dispatcher_isolates_provider_failure_and_persists_attempts():
    database = Database(Path(":memory:")); database.open()
    repository = NotificationRepository(database)
    results = await NotificationDispatcher([FailingProvider(), SuccessfulProvider()], repository).dispatch(_record())

    assert [(result.provider, result.success) for result in results] == [("failure", False), ("success", True)]
    attempts = repository.get_for_signal("ETHUSDT-15m-BULLISH-test-100")
    assert [(attempt.provider, attempt.success) for attempt in attempts] == [("failure", False), ("success", True)]
    database.close()
