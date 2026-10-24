"""Drive the Streamlit app headlessly through the demo workflow."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def app(monkeypatch):
    # An empty environment variable overrides any key in a local .env file.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    from pitch90.config import get_settings

    get_settings.cache_clear()
    at = AppTest.from_file(APP, default_timeout=300)
    at.run()
    yield at
    get_settings.cache_clear()


def click(at: AppTest, label: str) -> None:
    next(b for b in at.button if b.label == label).click()
    at.run()


def test_demo_workflow_end_to_end(app):
    at = app
    assert not at.exception
    assert at.sidebar.radio[0].value.startswith("Demo")  # no key -> demo by default

    click(at, "Try the synthetic sample deck")
    assert not at.exception
    headers = [h.value for h in at.header]
    assert "2 · Review extracted content" in headers
    warnings_text = " ".join(w.value for w in at.warning) + " ".join(i.value for i in at.info)
    assert "instructions to an AI system" in warnings_text

    click(at, "Run demo analysis")
    assert not at.exception
    assert any(m.value == "17 / 25" for m in at.metric)
    assert any("Fits on one US Letter page" in s.value for s in at.success)
    assert "6 · Download" in [h.value for h in at.header]


def test_api_mode_requires_key_and_consent(app):
    at = app
    at.sidebar.radio[0].set_value("Anthropic API").run()
    click(at, "Try the synthetic sample deck")
    run_button = next(b for b in at.button if b.label == "Run analysis")
    assert run_button.disabled
    assert any("ANTHROPIC_API_KEY" in w.value for w in at.warning)


@pytest.fixture
def secured_app(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("APP_PASSWORD", "correct horse")
    monkeypatch.setenv("APP_USERNAME", "ten")
    from pitch90.config import get_settings

    get_settings.cache_clear()
    at = AppTest.from_file(APP, default_timeout=300)
    at.run()
    yield at
    get_settings.cache_clear()


def test_sign_in_required_when_password_set(secured_app):
    at = secured_app
    assert not any(b.label == "Try the synthetic sample deck" for b in at.button)
    at.text_input[0].set_value("ten")
    at.text_input[1].set_value("wrong")
    at.button[0].click()
    at.run()
    assert any("Incorrect" in e.value for e in at.error)
    assert not any(b.label == "Try the synthetic sample deck" for b in at.button)

    at.text_input[1].set_value("correct horse")
    at.button[0].click()
    at.run()
    assert any(b.label == "Try the synthetic sample deck" for b in at.button)


def test_results_emailed_after_analysis(monkeypatch):
    import io
    import json

    from pitch90 import mailer

    sent = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(request, timeout):
        sent.append(json.loads(request.data))
        return Resp(b'{"id": "msg_1"}')

    monkeypatch.setattr(mailer.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("EMAIL_DEMO_RUNS", "true")
    from pitch90.config import get_settings

    get_settings.cache_clear()
    try:
        at = AppTest.from_file(APP, default_timeout=300)
        at.run()
        click(at, "Try the synthetic sample deck")
        click(at, "Run demo analysis")
        assert not at.exception
        assert len(sent) == 1
        names = [a["filename"] for a in sent[0]["attachments"]]
        assert names == ["tidewell_sample_deck_onepager.pdf", "tidewell_sample_deck_analysis_report.pdf",
                         "tidewell_sample_deck_analysis.json"]
        assert sent[0]["to"] == ["Info@tencapital.group"]
        assert "[demo]" in sent[0]["subject"]
        assert any("Results emailed" in s.value for s in at.success)
    finally:
        get_settings.cache_clear()


def test_api_mode_proceeds_from_extraction_to_findings(monkeypatch):
    """No consent checkbox or other gate: one click runs the analysis to completion."""
    from pitch90.demo import demo_analysis
    from pitch90.llm import AnthropicAnalyzer

    calls = []

    def fake_analyze(self, deck, progress=None):
        calls.append(deck.filename)
        if progress:
            progress("Writing the analysis", 1.0, 100)
        return demo_analysis(deck), []

    monkeypatch.setattr(AnthropicAnalyzer, "analyze", fake_analyze)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("RESEND_API_KEY", "")
    from pitch90.config import get_settings

    get_settings.cache_clear()
    try:
        at = AppTest.from_file(APP, default_timeout=300)
        at.run()
        assert at.sidebar.radio[0].value == "Anthropic API"
        click(at, "Try the synthetic sample deck")
        assert not at.checkbox  # no consent gate
        click(at, "Run analysis")
        assert not at.exception
        assert calls == ["tidewell_sample_deck.pptx"]
        assert any(m.value == "17 / 25" for m in at.metric)
        assert not next(b for b in at.button if b.label == "Run analysis").disabled
    finally:
        get_settings.cache_clear()
