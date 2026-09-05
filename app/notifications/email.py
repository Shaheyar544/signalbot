from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from app.notifications.base import DeliveryResult
from app.notifications.formatting import format_signal
from app.signals.models import SignalRecord


class SMTPEmailProvider:
    name = "email"

    def __init__(self, host: str, port: int, username: str, password: str, sender: str, recipient: str) -> None:
        self.host, self.port, self.username, self.password, self.sender, self.recipient = host, port, username, password, sender, recipient

    async def send(self, signal: SignalRecord) -> DeliveryResult:
        message = EmailMessage()
        message["Subject"] = f"{signal.symbol} {signal.direction} {signal.classification}"
        message["From"], message["To"] = self.sender, self.recipient
        message.set_content(format_signal(signal))
        try:
            await asyncio.to_thread(self._send, message)
            return DeliveryResult(self.name, True)
        except (OSError, smtplib.SMTPException) as error:
            return DeliveryResult(self.name, False, str(error))

    def _send(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self.host, self.port, timeout=15) as client:
            client.starttls()
            if self.username:
                client.login(self.username, self.password)
            client.send_message(message)
