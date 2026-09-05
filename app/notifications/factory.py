from __future__ import annotations

import logging
import os

from app.notifications.discord import DiscordWebhookProvider
from app.notifications.email import SMTPEmailProvider
from app.notifications.base import NotificationProvider
from app.notifications.whatsapp import WhatsAppCloudProvider

LOGGER = logging.getLogger(__name__)


def _enabled(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes"}


def configured_providers() -> list[NotificationProvider]:
    providers: list[NotificationProvider] = []
    if _enabled("DISCORD_ENABLED"):
        url = os.getenv("DISCORD_WEBHOOK_URL")
        if url:
            providers.append(DiscordWebhookProvider(url))
        else:
            LOGGER.error("Discord is enabled but DISCORD_WEBHOOK_URL is missing")
    if _enabled("WHATSAPP_ENABLED"):
        token, phone_id, recipient = os.getenv("WHATSAPP_TOKEN"), os.getenv("WHATSAPP_PHONE_NUMBER_ID"), os.getenv("WHATSAPP_RECIPIENT")
        if token and phone_id and recipient:
            providers.append(WhatsAppCloudProvider(token, phone_id, recipient))
        else:
            LOGGER.error("WhatsApp is enabled but required configuration is missing")
    if _enabled("EMAIL_ENABLED"):
        host, sender, recipient = os.getenv("SMTP_HOST"), os.getenv("EMAIL_FROM"), os.getenv("EMAIL_TO")
        if host and sender and recipient:
            providers.append(SMTPEmailProvider(host, int(os.getenv("SMTP_PORT", "587")), os.getenv("SMTP_USERNAME", ""), os.getenv("SMTP_PASSWORD", ""), sender, recipient))
        else:
            LOGGER.error("Email is enabled but required configuration is missing")
    return providers
