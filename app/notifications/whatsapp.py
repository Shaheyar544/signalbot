from __future__ import annotations

import aiohttp

from app.notifications.base import DeliveryResult
from app.notifications.formatting import format_signal
from app.signals.models import SignalRecord


class WhatsAppCloudProvider:
    name = "whatsapp"

    def __init__(self, token: str, phone_number_id: str, recipient: str, api_version: str = "v20.0") -> None:
        self.token, self.phone_number_id, self.recipient, self.api_version = token, phone_number_id, recipient, api_version

    async def send(self, signal: SignalRecord) -> DeliveryResult:
        url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
        payload = {"messaging_product": "whatsapp", "to": self.recipient, "type": "text", "text": {"body": format_signal(signal)}}
        headers = {"Authorization": f"Bearer {self.token}"}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if 200 <= response.status < 300:
                    return DeliveryResult(self.name, True)
                return DeliveryResult(self.name, False, f"WhatsApp HTTP {response.status}")
