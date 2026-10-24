from __future__ import annotations

import base64
import io
import json
import urllib.error

import pytest

from pitch90 import mailer
from pitch90.analysis import finalize
from pitch90.config import Settings
from pitch90.mailer import Attachment, build_payload, send

KEY = "re_test_secret_key"


@pytest.fixture
def result(sample_deck, demo_llm):
    return finalize(demo_llm, sample_deck, mode="api", model="claude-opus-5-5",
                    words_per_minute=140, images_sent=[])


@pytest.fixture
def mail_settings() -> Settings:
    return Settings(RESEND_API_KEY=KEY, _env_file=None)


ATTACHMENTS = [Attachment("deck_onepager.pdf", b"%PDF-1.4 one"), Attachment("deck_analysis.json", b"{}")]


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_default_recipient_and_disabled_without_key():
    s = Settings(RESEND_API_KEY=None, _env_file=None)
    assert s.report_recipients == ["Info@tencapital.group"]
    assert not s.email_enabled
    outcome = send(None, [], s)  # type: ignore[arg-type]
    assert not outcome.sent and "RESEND_API_KEY" in outcome.detail


def test_payload_contents(result, mail_settings):
    payload = build_payload(result, ATTACHMENTS, mail_settings)
    assert payload["to"] == ["Info@tencapital.group"]
    assert payload["from"].endswith("@tencapital.group>")
    assert "17/25 (68%)" in payload["subject"] and result.company_name in payload["subject"]
    assert [a["filename"] for a in payload["attachments"]] == ["deck_onepager.pdf", "deck_analysis.json"]
    assert base64.b64decode(payload["attachments"][0]["content"]) == b"%PDF-1.4 one"
    for fix in result.priority_fixes:
        assert fix in payload["text"]
    assert "Customer and problem" in payload["html"]
    assert KEY not in json.dumps(payload)


def test_html_escapes_deck_content(result, mail_settings):
    odd = result.model_copy(update={"company_name": "<script>x</script> & Co"})
    html = build_payload(odd, [], mail_settings)["html"]
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_multiple_recipients():
    s = Settings(RESEND_API_KEY=KEY, REPORT_EMAIL_TO="a@x.com, b@y.com", _env_file=None)
    assert s.report_recipients == ["a@x.com", "b@y.com"]


def test_oversized_attachment_dropped_with_note(result, mail_settings, monkeypatch):
    monkeypatch.setattr(mailer, "MAX_TOTAL_ATTACHMENT_BYTES", 13)
    payload = build_payload(result, ATTACHMENTS, mail_settings)
    assert [a["filename"] for a in payload["attachments"]] == ["deck_onepager.pdf"]
    assert "too large" in payload["text"]


def test_send_success(result, mail_settings, monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        return FakeResponse(b'{"id": "msg_123"}')

    monkeypatch.setattr(mailer.urllib.request, "urlopen", fake_urlopen)
    outcome = send(result, ATTACHMENTS, mail_settings)
    assert outcome.sent and outcome.message_id == "msg_123"
    assert "Info@tencapital.group" in outcome.detail
    req = captured["request"]
    assert req.full_url == "https://api.resend.com/emails"
    assert req.get_header("Authorization") == f"Bearer {KEY}"
    assert req.get_header("User-agent").startswith("pitch90/")


def test_send_rejected_reports_resend_message(result, mail_settings, monkeypatch):
    def reject(request, timeout):
        body = io.BytesIO(b'{"message": "The tencapital.group domain is not verified."}')
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, body)

    monkeypatch.setattr(mailer.urllib.request, "urlopen", reject)
    outcome = send(result, ATTACHMENTS, mail_settings)
    assert not outcome.sent
    assert "403" in outcome.detail and "not verified" in outcome.detail
    assert KEY not in outcome.detail


def test_send_network_failure_never_raises(result, mail_settings, monkeypatch):
    def down(request, timeout):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(mailer.urllib.request, "urlopen", down)
    outcome = send(result, ATTACHMENTS, mail_settings)
    assert not outcome.sent and "Could not reach Resend" in outcome.detail

    monkeypatch.setattr(mailer.urllib.request, "urlopen", lambda r, timeout: (_ for _ in ()).throw(TimeoutError("slow")))
    assert not send(result, ATTACHMENTS, mail_settings).sent
