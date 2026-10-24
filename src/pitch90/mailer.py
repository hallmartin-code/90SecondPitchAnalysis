"""Emailing each analysis result via Resend.

A send that fails must never fail an analysis: the results on screen and the downloads are
the product, the email is a notification about them. Every failure is caught and returned
as an ``EmailOutcome``; nothing here raises, and the API key is never logged or echoed.

Resend's API is a single JSON POST, so it goes through ``urllib`` rather than adding the
``resend`` SDK as a dependency.
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from html import escape
from typing import Any

from pitch90.config import Settings
from pitch90.framework import ELEMENT_TITLES, RUBRIC_LEVELS
from pitch90.models import AnalysisResult

log = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"
# Resend sits behind Cloudflare, which rejects urllib's default agent with a 403 (error 1010).
USER_AGENT = "pitch90/1.0 (+https://tencapital.group)"
MAX_TOTAL_ATTACHMENT_BYTES = 35 * 1024 * 1024  # Resend's limit is 40 MB per message
TIMEOUT_S = 20.0


@dataclass(frozen=True)
class EmailOutcome:
    sent: bool
    detail: str
    message_id: str | None = None


@dataclass(frozen=True)
class Attachment:
    filename: str
    content: bytes


def describe(settings: Settings) -> str:
    """One line for the UI saying what will happen after the next analysis."""
    if not settings.email_enabled:
        return "Email off: RESEND_API_KEY is not set."
    return f"Results are emailed to {settings.report_email_to} after each analysis."


def subject_for(result: AnalysisResult) -> str:
    label = " [demo]" if result.mode == "demo" else ""
    return (f"{result.company_name} - 90-Second Pitch Analysis: "
            f"{result.total_score}/{result.max_score} ({result.percentage:.0f}%){label}")


def _pages(pages: list[int], unit: str) -> str:
    return f" ({unit.capitalize()} {', '.join(map(str, pages))})" if pages else ""


def _list(items: list[str]) -> str:
    if not items:
        return "<p style='margin:0;color:#6b7280'>None identified.</p>"
    rows = "".join(f"<li style='margin:0 0 4px'>{escape(i)}</li>" for i in items)
    return f"<ul style='margin:0;padding-left:18px'>{rows}</ul>"


def _heading(text: str) -> str:
    return (f"<div style='font-weight:600;font-size:13px;color:#1f3a5f;text-transform:uppercase;"
            f"letter-spacing:.05em;margin:18px 0 6px'>{escape(text)}</div>")


def build_html(result: AnalysisResult, attachment_names: list[str], notes: list[str]) -> str:
    unit = result.unit_label
    rows = "".join(
        f"<tr><td style='padding:5px 8px;border-bottom:1px solid #e5e7eb'>{escape(ELEMENT_TITLES[e.element])}</td>"
        f"<td style='padding:5px 8px;border-bottom:1px solid #e5e7eb;text-align:center'>{e.score}/5</td>"
        f"<td style='padding:5px 8px;border-bottom:1px solid #e5e7eb;color:#6b7280'>{escape(RUBRIC_LEVELS[e.score])}</td></tr>"
        for e in result.elements
    )
    strongest = [p.text + _pages(p.source_pages, unit) for p in result.strongest_points]
    inconsistencies = [i.description for i in result.inconsistencies]
    flagged = sum(1 for w in result.extraction_warnings if w.severity in ("warning", "error"))
    caveats = list(notes)
    if result.mode == "demo":
        caveats.insert(0, "Demo run on the bundled synthetic sample deck; not a real company.")
    if flagged:
        caveats.append(f"{flagged} extraction warning(s); see the report's extraction limitations.")
    if result.validation_warnings:
        caveats.append(f"{len(result.validation_warnings)} automated validation warning(s) in the report.")
    files = ", ".join(attachment_names) or "none"

    return f"""<div style="font:14px/1.5 -apple-system,'Segoe UI',Helvetica,Arial,sans-serif;color:#14181f;max-width:660px">
  <div style="border-bottom:2px solid #1f3a5f;padding-bottom:10px;margin-bottom:14px">
    <div style="font-weight:700;font-size:20px">{escape(result.company_name)}</div>
    <div style="color:#6b7280;font-size:12px;margin-top:4px">90-Second Pitch Analysis · narrative score
      <b style="color:#14181f">{result.total_score}/{result.max_score} ({result.percentage:.0f}%)</b></div>
  </div>
  <table style="border-collapse:collapse;width:100%;font-size:13px">{rows}</table>
  {_heading("Three strongest narrative points")}{_list(strongest)}
  {_heading("Three highest-priority fixes")}{_list(result.priority_fixes)}
  {_heading("Numerical inconsistencies")}{_list(inconsistencies)}
  {_heading("Information gaps")}{_list(result.information_gaps)}
  {_heading("Caveats")}{_list(caveats) if caveats else "<p style='margin:0;color:#6b7280'>Nothing flagged.</p>"}
  <div style="font-size:12px;color:#6b7280;border-top:1px solid #e5e7eb;padding-top:10px;margin-top:20px">
    Attached: {escape(files)}<br>
    Source: {escape(result.source_filename)} · mode {escape(result.mode)} · model {escape(result.model or "none")} · {escape(result.created_at)}<br>
    {escape(result.disclaimer)}<br>
    Generated by TEN Capital · Internal use only.
  </div>
</div>"""


def build_text(result: AnalysisResult, attachment_names: list[str], notes: list[str]) -> str:
    lines = [
        result.company_name,
        f"90-Second Pitch Analysis - narrative score {result.total_score}/{result.max_score} "
        f"({result.percentage:.0f}%)" + (" [demo, synthetic deck]" if result.mode == "demo" else ""),
        "",
    ]
    lines += [f"  {ELEMENT_TITLES[e.element]}: {e.score}/5" for e in result.elements]
    lines += ["", "STRONGEST POINTS"] + [f"  - {p.text}" for p in result.strongest_points]
    lines += ["", "PRIORITY FIXES"] + [f"  - {f}" for f in result.priority_fixes]
    lines += ["", "INCONSISTENCIES"] + ([f"  - {i.description}" for i in result.inconsistencies] or ["  - None identified."])
    lines += ["", "INFORMATION GAPS"] + ([f"  - {g}" for g in result.information_gaps] or ["  - None identified."])
    if notes:
        lines += ["", "NOTES"] + [f"  - {n}" for n in notes]
    lines += [
        "",
        f"Attached: {', '.join(attachment_names) or 'none'}",
        f"Source: {result.source_filename} ({result.mode}, {result.model or 'no model'})",
        result.disclaimer,
        "Generated by TEN Capital - internal use only.",
    ]
    return "\n".join(lines)


def build_payload(result: AnalysisResult, attachments: list[Attachment], settings: Settings,
                  notes: list[str] | None = None) -> dict[str, Any]:
    """The Resend request body. Separate from sending so it can be tested offline."""
    notes = list(notes or [])
    kept, total = [], 0
    for a in attachments:
        if total + len(a.content) > MAX_TOTAL_ATTACHMENT_BYTES:
            notes.append(f"{a.filename} was too large to attach; download it from the app.")
            continue
        kept.append(a)
        total += len(a.content)
    names = [a.filename for a in kept]
    return {
        "from": settings.report_email_from,
        "to": settings.report_recipients,
        "subject": subject_for(result),
        "html": build_html(result, names, notes),
        "text": build_text(result, names, notes),
        "attachments": [
            {"filename": a.filename, "content": base64.standard_b64encode(a.content).decode("ascii")}
            for a in kept
        ],
    }


def send(result: AnalysisResult, attachments: list[Attachment], settings: Settings,
         notes: list[str] | None = None) -> EmailOutcome:
    """Email the result. Returns what happened; never raises, never logs the key."""
    if not settings.email_enabled:
        return EmailOutcome(False, "RESEND_API_KEY is not set; the result was not emailed.")
    payload = build_payload(result, attachments, settings, notes)
    request = urllib.request.Request(  # noqa: S310 - fixed https endpoint
        RESEND_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.resend_api_key.get_secret_value()}",  # type: ignore[union-attr]
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
            body = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = _readable(exc.read().decode("utf-8", "replace")[:400])
        log.warning("Resend rejected the message (%s)", exc.code)
        return EmailOutcome(False, f"Resend rejected the email ({exc.code}): {detail}")
    except urllib.error.URLError as exc:
        return EmailOutcome(False, f"Could not reach Resend: {exc.reason}")
    except (TimeoutError, json.JSONDecodeError, OSError) as exc:
        return EmailOutcome(False, f"Emailing the result failed: {exc}")
    message_id = str(body.get("id")) if isinstance(body, dict) and body.get("id") else None
    log.info("Result emailed (Resend id %s)", message_id)
    return EmailOutcome(True, f"Results emailed to {', '.join(settings.report_recipients)}.", message_id)


def _readable(body: str) -> str:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body
    if isinstance(parsed, dict):
        return str(parsed.get("message") or parsed.get("error") or body)
    return body
