from __future__ import annotations

import aiohttp

from app.notifications.base import DeliveryResult
from app.notifications.formatting import format_signal
from app.signals.models import SignalRecord


class DiscordWebhookProvider:
    name = "discord"

    def __init__(self, webhook_url: str) -> None:
        self.webhook_url = webhook_url

    async def send(self, signal: SignalRecord) -> DeliveryResult:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(self.webhook_url, json={"content": format_signal(signal)}) as response:
                if 200 <= response.status < 300:
                    return DeliveryResult(self.name, True)
                return DeliveryResult(self.name, False, f"Discord HTTP {response.status}")
