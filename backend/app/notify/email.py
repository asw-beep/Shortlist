"""Sending email. A port: code depends on EmailSender, and the implementation can change.

Two senders. Tests and laptops use the in-memory one. Deployed, Brevo's HTTP API sends:
Render's free tier blocks outbound SMTP ports (25, 465, 587), so plain SMTP can't work
there. Neither logs a message body, because bodies carry secrets such as reset links.
"""

from collections import deque
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
import structlog

log = structlog.get_logger(__name__)
BREVO_URL = "https://api.brevo.com/v3/smtp/email"


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str
    html: str | None = None


class EmailError(Exception):
    pass


class EmailSender(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class InMemoryEmailSender:
    """Keeps the most recent messages; nothing leaves the process."""

    def __init__(self, keep: int = 100) -> None:
        self._sent: deque[EmailMessage] = deque(maxlen=keep)

    @property
    def sent(self) -> list[EmailMessage]:
        return list(self._sent)

    def send(self, message: EmailMessage) -> None:
        self._sent.append(message)
        log.info("email.sent", subject=message.subject)  # no address and no body: PII, secrets


class BrevoEmailSender:
    def __init__(
        self, *, api_key: str, sender_email: str, sender_name: str, client: httpx.Client
    ) -> None:
        self._api_key, self._client = api_key, client
        self._sender = {"name": sender_name, "email": sender_email}

    def send(self, message: EmailMessage) -> None:
        payload: dict[str, Any] = {
            "sender": self._sender,
            "to": [{"email": message.to}],
            "subject": message.subject,
            "textContent": message.body,
        }
        if message.html is not None:
            payload["htmlContent"] = message.html
        try:
            response = self._client.post(
                BREVO_URL, json=payload, headers={"api-key": self._api_key}, timeout=15
            )
        except httpx.HTTPError as error:
            raise EmailError(f"Brevo unreachable ({type(error).__name__})") from error
        if response.status_code >= 300:
            raise EmailError(f"Brevo refused the message: HTTP {response.status_code}")
        log.info("email.sent", subject=message.subject, provider="brevo")
