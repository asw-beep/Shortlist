"""Brevo's transactional email API over HTTPS (Render Free blocks SMTP ports)."""

import json

import httpx
import pytest

from app.notify.email import BrevoEmailSender, EmailError, EmailMessage


def sender_with(handler) -> BrevoEmailSender:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return BrevoEmailSender(
        api_key="secret",
        sender_email="shortlist@example.in",
        sender_name="Shortlist",
        client=client,
    )


def test_brevo_payload_and_headers() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers["api-key"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"messageId": "m1"})

    sender_with(handler).send(
        EmailMessage(to="asha@example.in", subject="Your digest", body="Text", html="<p>Text</p>")
    )
    assert seen["url"] == "https://api.brevo.com/v3/smtp/email"
    assert seen["key"] == "secret"
    assert seen["body"] == {
        "sender": {"name": "Shortlist", "email": "shortlist@example.in"},
        "to": [{"email": "asha@example.in"}],
        "subject": "Your digest",
        "textContent": "Text",
        "htmlContent": "<p>Text</p>",
    }


def test_brevo_omits_html_when_absent() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(201, json={})

    sender_with(handler).send(EmailMessage(to="a@example.in", subject="S", body="B"))
    assert "htmlContent" not in seen


def test_brevo_non_2xx_raises() -> None:
    with pytest.raises(EmailError):
        sender_with(lambda r: httpx.Response(401, json={"code": "unauthorized"})).send(
            EmailMessage(to="a@example.in", subject="S", body="B")
        )


def test_brevo_transport_failure_raises() -> None:
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(EmailError):
        sender_with(handler).send(EmailMessage(to="a@example.in", subject="S", body="B"))
