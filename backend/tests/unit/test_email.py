"""Where email goes: an in-memory list in tests and on a laptop, Brevo when a key is set."""

from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_email_sender
from app.notify.email import BrevoEmailSender, EmailMessage, InMemoryEmailSender


def test_in_memory_sender_keeps_messages() -> None:
    sender = InMemoryEmailSender()
    sender.send(EmailMessage(to="a@example.in", subject="Hi", body="Hello"))
    assert [m.subject for m in sender.sent] == ["Hi"]


def test_without_a_brevo_key_email_stays_in_memory() -> None:
    sender = create_email_sender(Settings(_env_file=None, environment="test"))
    assert isinstance(sender, InMemoryEmailSender)


def test_with_a_brevo_key_email_goes_to_brevo() -> None:
    settings = Settings(_env_file=None, environment="test", brevo_api_key=SecretStr("k"))
    assert isinstance(create_email_sender(settings), BrevoEmailSender)
