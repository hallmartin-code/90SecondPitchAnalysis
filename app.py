"""Streamlit interface: upload -> review extraction -> analyse -> review/correct -> export.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import sys
import threading
import time
from pathlib import Path

import pymupdf
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from pitch90.analysis import SECTION_FIELDS, finalize, onepager_figure_warnings  # noqa: E402
from pitch90.config import get_settings  # noqa: E402
from pitch90.demo import SAMPLE_DECK, DemoUnavailable, demo_analysis, is_sample_deck  # noqa: E402
from pitch90.evidence import apply_user_correction, mark_conflicts  # noqa: E402
from pitch90.framework import ARTICLE_URL, ELEMENT_GUIDANCE, ELEMENT_TITLES, FRAMEWORK_SUMMARY, RUBRIC, RUBRIC_LEVELS  # noqa: E402
from pitch90.ingest import ConversionFailed, ConversionUnavailable, UploadError, extract_deck  # noqa: E402
from pitch90.ingest.convert import find_soffice  # noqa: E402
from pitch90.ingest.ocr import ocr_available  # noqa: E402
from pitch90.llm import AnthropicAnalyzer, LLMError  # noqa: E402
from pitch90.mailer import Attachment, EmailOutcome  # noqa: E402
from pitch90.mailer import describe as describe_email  # noqa: E402
from pitch90.mailer import send as send_email  # noqa: E402
from pitch90.models import NOT_PROVIDED, AnalysisResult, LLMOnePager, OnePagerSection, TeamMember  # noqa: E402
from pitch90.render.onepager import render_onepager, shorten_to_fit  # noqa: E402
from pitch90.render.report import export_json, render_report  # noqa: E402
from pitch90.render.template import TemplateError  # noqa: E402
from pitch90.scoring import PITCH_MAX_WORDS, PITCH_MIN_WORDS, pitch_timing  # noqa: E402
from pitch90.ui import theme  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
FAVICON = Path(__file__).resolve().parent / "static" / "favicon.png"
st.set_page_config(page_title="90-Second Pitch Test | TEN Capital", page_icon=str(FAVICON), layout="wide")
settings = get_settings()
ss = st.session_state

SECTION_LABELS = {
    "positioning": "Positioning statement",
    "problem_why_now": "Problem & why now",
    "solution_benefit": "Solution & customer benefit",
    "market_business_model": "Market & business model",
    "traction_evidence": "Traction & evidence",
    "differentiation": "Differentiation",
    "fundraising_target": "Fundraising target",
    "terms": "Disclosed terms",
    "use_of_funds": "Use of funds",
    "milestones": "Milestones",
    "exit_strategy": "Exit strategy (only if in the deck)",
    "contact": "Contact (only if in the deck)",
}


def reset(keep_deck: bool = False) -> None:
    keys = ["result", "onepager", "onepager_orig", "edits", "shorten_log", "facts", "email_outcome"]
    if not keep_deck:
        keys += ["deck", "deck_key", "upload_error"]
    for k in keys:
        ss.pop(k, None)


def cite_label(pages: list[int]) -> str:
    deck = ss.get("deck")
    if not pages or deck is None:
        return "–"
    return f"{deck.unit_label.capitalize()} {', '.join(map(str, pages))}"


def email_results(res: AnalysisResult, deck) -> EmailOutcome:
    """Render the deliverables for ``res`` and email them; never raises."""
    attachments, notes = [], []
    stem = Path(deck.filename).stem
    try:
        pdf, fit = render_onepager(res.onepager, "p" if deck.unit_label == "page" else "S")
        if pdf:
            attachments.append(Attachment(f"{stem}_onepager.pdf", pdf))
        else:
            notes.append("The one-pager does not fit on one page yet and was not attached: " + fit.message)
        attachments.append(Attachment(f"{stem}_analysis_report.pdf", render_report(res)))
    except Exception as exc:  # a rendering problem must not block the email or the run
        logging.exception("Rendering attachments for email failed")
        notes.append(f"Some attachments could not be generated ({type(exc).__name__}).")
    attachments.append(Attachment(f"{stem}_analysis.json", export_json(res).encode("utf-8")))
    return send_email(res, attachments, settings, notes)


@st.cache_resource
def analysis_slots() -> threading.BoundedSemaphore:
    """Process-wide cap on concurrent paid API analyses (shared by all browser sessions)."""
    return threading.BoundedSemaphore(max(1, settings.max_concurrent_analyses))


# ------------------------------------------------------------------ sign-in

st.markdown(theme.CSS, unsafe_allow_html=True)
st.markdown(theme.brand_html(), unsafe_allow_html=True)


def stop() -> None:
    """Render the footer, then end this script run."""
    st.markdown(theme.FOOTER_HTML, unsafe_allow_html=True)
    st.stop()


if settings.auth_enabled and not ss.get("authenticated"):
    with st.container(key="signin"), st.form("sign_in"):
        st.markdown('<div class="ten-eyebrow">Sign in</div>', unsafe_allow_html=True)
        user = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in", type="primary", width="stretch"):
            expected = settings.app_password.get_secret_value()  # type: ignore[union-attr]
            ok_user = hmac.compare_digest(user.strip().encode(), settings.app_username.encode())
            ok_pass = hmac.compare_digest(password.encode(), expected.encode())
            if ok_user and ok_pass:
                ss.authenticated = True
                st.rerun()
            time.sleep(1.5)  # slow down guessing
            st.error("Incorrect username or password.")
    stop()

# ------------------------------------------------------------------ sidebar

with st.sidebar:
    st.header("Settings")
    mode = st.radio(
        "Analysis mode",
        ["Anthropic API", "Demo (synthetic sample, no API)"],
        index=0 if settings.has_api_key else 1,
        help="Demo mode analyses only the bundled fictional sample deck using pre-written output.",
    )
    demo_mode = mode.startswith("Demo")
    wpm = st.number_input("Speaking rate (words per minute)", 90, 220, settings.words_per_minute, step=5)
    st.divider()
    st.caption("Environment")
    st.write(("✅" if settings.has_api_key else "⚠️") + " API key " + ("configured" if settings.has_api_key else "not configured"))
    st.write(f"Model: `{settings.model}` · effort `{settings.effort}`")
    if settings.has_api_key and st.button("Test API connection", width="stretch",
                                          help="Checks the key and model with a free Models API lookup."):
        try:
            st.success(AnthropicAnalyzer(settings).check_connection())
        except LLMError as exc:
            st.error(str(exc))
    st.write(("✅" if ocr_available() else "⚠️") + " Local OCR " + ("available" if ocr_available() else "unavailable"))
    soffice = find_soffice(settings.soffice_path)
    st.write(("✅" if soffice else "⚠️") + " LibreOffice " + ("found" if soffice else "not found (.ppt and slide rendering unavailable)"))
    st.divider()
    st.caption(
        "**Data notice:** in API mode, clicking *Run analysis* sends the extracted deck text, speaker "
        "notes and selected slide/page images to Anthropic's API for processing. Nothing is sent "
        "before you click. Demo mode makes no network calls."
        + (f" A copy of each analysis (summary, one-pager, report and JSON) is emailed to "
           f"{settings.report_email_to} via Resend." if settings.email_enabled else "")
    )
    st.write(("📧 " if settings.email_enabled else "✉️ ") + describe_email(settings))
    if st.button("Start over", width="stretch"):
        reset()
        st.rerun()
    if settings.railway_environment and not settings.auth_enabled:
        st.error("This deployment has no APP_PASSWORD: anyone with the URL can run paid analyses "
                 "on your API key. Set APP_PASSWORD in Railway.")

# ------------------------------------------------------------------ 1. upload (hero card)

with st.container(key="hero"):
    st.markdown(theme.hero_html(), unsafe_allow_html=True)
    upload = st.file_uploader(
        f"Choose a deck: PDF, PPTX or PPT (max {settings.max_upload_mb} MB)", type=["pdf", "pptx", "ppt"],
        accept_multiple_files=False, label_visibility="collapsed",
    )
    load_sample = st.button("Try the synthetic sample deck", width="stretch",
                            help="A fictional company deck with deliberate test conditions.")
    st.markdown(theme.disclosure_html(".pdf · .pptx · .ppt", settings.max_upload_mb,
                                      settings.report_email_to if settings.email_enabled else None),
                unsafe_allow_html=True)


def run_extraction(name: str, data: bytes) -> None:
    key = hashlib.sha256(data).hexdigest() + name
    if ss.get("deck_key") == key:
        return
    reset()
    ss.deck_key = key
    with st.spinner("Extracting content (OCR and slide rendering can take a minute)…"):
        try:
            ss.deck = extract_deck(name, data, settings)
        except ConversionUnavailable as exc:
            ss.upload_error = f"Cannot open legacy .ppt: {exc}"
        except (UploadError, ConversionFailed) as exc:
            ss.upload_error = str(exc)
        except Exception:  # pragma: no cover - surface unexpected failures cleanly
            logging.exception("Extraction failed")
            ss.upload_error = "The file could not be processed. It may be corrupt or in an unsupported format."


if load_sample:
    run_extraction(SAMPLE_DECK.name, SAMPLE_DECK.read_bytes())
elif upload is not None:
    run_extraction(upload.name, upload.getvalue())

if ss.get("upload_error"):
    st.error(ss.upload_error)

deck = ss.get("deck")
st.markdown(theme.steps_html(3 if ss.get("result") else 2 if deck else 0), unsafe_allow_html=True)
with st.expander("How the 90-second test works: framework and scoring rubric"):
    st.caption("Evaluates whether a deck tells a compelling company story in 90 seconds, using Andy Raskin's "
               "narrative structure. Narrative quality only; not an assessment of investment merit.")
    st.markdown(f"Source: [{ARTICLE_URL}]({ARTICLE_URL}) (summary stored locally)")
    st.text(FRAMEWORK_SUMMARY)
    st.text(RUBRIC)
if deck is None:
    stop()

# ------------------------------------------------------------------ 2. review extraction

st.header("2 · Review extracted content")
label = deck.unit_label
st.write(f"**{deck.filename}** · {len(deck.units)} {label}s · "
         f"{sum(1 for u in deck.units if u.notes)} with speaker notes · "
         f"{sum(1 for u in deck.units if u.ocr_text)} read by OCR · "
         f"{sum(1 for u in deck.units if u.needs_visual)} relying on visuals")

st.subheader("Extraction warnings")
if not deck.warnings:
    st.success("No extraction warnings.")
for w in sorted(deck.warnings, key=lambda w: {"error": 0, "warning": 1, "info": 2}[w.severity]):
    where = f" ({label}s {', '.join(map(str, w.units))})" if w.units else ""
    {"error": st.error, "warning": st.warning, "info": st.info}[w.severity](w.message + where)

with st.expander(f"View content by {label} (original numbering)"):
    for u in deck.units:
        flags = []
        if u.hidden:
            flags.append("hidden")
        if u.ocr_text:
            flags.append("OCR")
        if u.needs_visual:
            flags.append("visual")
        st.markdown(f"**{label.capitalize()} {u.number}**" + (f" · _{', '.join(flags)}_" if flags else ""))
        cols = st.columns([3, 2]) if u.number in deck.images else [st.container()]
        with cols[0]:
            st.text(u.text or "(no extractable text)")
            for t in u.tables:
                st.table(t)
            for c in u.chart_data:
                st.caption(f"Chart data: {c}")
            if u.ocr_text:
                st.caption("OCR text (check for recognition errors):")
                st.text(u.ocr_text)
            if u.notes:
                st.caption("Speaker notes (not visible on the slide):")
                st.text(u.notes)
        if u.number in deck.images:
            with cols[1]:
                st.image(deck.images[u.number], caption=f"{label} {u.number}: {u.visual_reason}")
        st.divider()

# ------------------------------------------------------------------ 3. analyse

st.header("3 · Run the analysis")
if demo_mode:
    if not is_sample_deck(deck):
        st.warning("Demo mode only analyses the bundled synthetic sample deck. Load it, or switch to API "
                   "mode (requires ANTHROPIC_API_KEY) to analyse this deck.")
    run = st.button("Run demo analysis", type="primary", disabled=not is_sample_deck(deck))
else:
    n_images = min(len(deck.images), settings.max_visual_pages)
    consent = st.checkbox(
        f"I understand that the extracted text and speaker notes of this deck"
        + (f", plus {n_images} {label} image(s)," if n_images else "")
        + f" will be sent to Anthropic's API (model {settings.model}) for analysis."
    )
    if not settings.has_api_key:
        st.warning("No ANTHROPIC_API_KEY is configured. Add it to a `.env` file (see `.env.example`) and "
                   "restart, or use demo mode. A Claude Code or claude.ai subscription does not include "
                   "API access; create an API key at platform.claude.com.")
    run = st.button("Run analysis", type="primary", disabled=not (consent and settings.has_api_key))

if run:
    reset(keep_deck=True)
    try:
        with st.spinner("Analysing the narrative… this can take a few minutes."):
            if demo_mode:
                llm, sent, model = demo_analysis(deck), [], None
            else:
                slots = analysis_slots()
                if not slots.acquire(timeout=1):
                    raise LLMError(f"{settings.max_concurrent_analyses} analyses are already running. "
                                   "Please try again in a few minutes.")
                try:
                    llm, sent = AnthropicAnalyzer(settings).analyze(deck)
                finally:
                    slots.release()
                model = settings.model
            result = finalize(llm, deck, mode="demo" if demo_mode else "api", model=model,
                              words_per_minute=int(wpm), images_sent=sent)
        ss.result = result
        ss.facts = [f.model_copy(deep=True) for f in result.facts]
        ss.onepager = result.onepager.model_copy(deep=True)
        ss.onepager_orig = result.onepager.model_copy(deep=True)
        ss.edits, ss.shorten_log = {}, []
        if settings.email_enabled and (not demo_mode or settings.email_demo_runs):
            with st.spinner(f"Emailing results to {settings.report_email_to}…"):
                ss.email_outcome = email_results(result, deck)
        st.rerun()  # refresh the step tracker, which was drawn before the analysis ran
    except (LLMError, DemoUnavailable) as exc:
        st.error(str(exc))
    except Exception:
        logging.exception("Analysis failed")
        st.error("The analysis failed unexpectedly. Please try again.")

result: AnalysisResult | None = ss.get("result")
if result is None:
    stop()

# ------------------------------------------------------------------ 4. findings

st.header("4 · Findings")
if ss.get("email_outcome"):
    outcome = ss.email_outcome
    (st.success if outcome.sent else st.warning)(("📧 " if outcome.sent else "Email not sent: ") + outcome.detail)
for wmsg in result.validation_warnings:
    st.warning(wmsg)

tab_score, tab_evidence, tab_pitch, tab_gaps = st.tabs(
    ["Narrative score", "Evidence & corrections", "90-second pitch", "Gaps & limitations"])

with tab_score:
    c1, c2 = st.columns(2)
    c1.metric("Narrative score", f"{result.total_score} / 25")
    c2.metric("Percentage", f"{result.percentage:.0f}%")
    st.caption("Narrative quality only, not investment merit. Extraction confidence is reported separately "
               "under *Gaps & limitations*.")
    st.dataframe(
        [{"Element": ELEMENT_TITLES[e.element], "Score": f"{e.score}/5", "Level": RUBRIC_LEVELS[e.score],
          "Sources": cite_label(e.source_pages)} for e in result.elements],
        width="stretch", hide_index=True,
    )
    for e in result.elements:
        with st.expander(f"{ELEMENT_TITLES[e.element]} — {e.score}/5"):
            st.caption(ELEMENT_GUIDANCE[e.element])
            st.write(e.rationale)
            st.write(f"**Sources:** {cite_label(e.source_pages)}")
            if e.missing_or_weak:
                st.write("**Missing or weak:**")
                for gap in e.missing_or_weak:
                    st.write(f"- {gap}")
            st.write(f"**Improvement:** {e.improvement}")
    if result.obstacle_capability_pairs:
        st.subheader("Obstacles → capabilities")
        st.dataframe([{"Obstacle": p.obstacle, "Capability": p.capability, "Sources": cite_label(p.source_pages)}
                      for p in result.obstacle_capability_pairs], width="stretch", hide_index=True)
    s1, s2 = st.columns(2)
    with s1:
        st.subheader("Three strongest points")
        for i, p in enumerate(result.strongest_points, 1):
            st.write(f"{i}. {p.text} _({cite_label(p.source_pages)})_")
    with s2:
        st.subheader("Three highest-priority fixes")
        for i, fix in enumerate(result.priority_fixes, 1):
            st.write(f"{i}. {fix}")

with tab_evidence:
    st.caption("Citations show where a claim appears in the deck; they do not verify it. Edit **Value**, "
               "**Unit** or **Period** to correct a fact; corrections are labelled user-provided and lose "
               "their deck citation.")
    st.subheader("Material numerical inconsistencies")
    if result.inconsistencies:
        for inc in result.inconsistencies:
            st.error(f"{inc.description}  \nValues: {'; '.join(inc.values)}")
    else:
        st.success("None identified.")
    rows = [{
        "ID": f.id, "Fact": f.label, "Value": f.value, "Unit": f.unit or "", "Period": f.period or "",
        "Basis": f.basis.value, "Commitment": f.commitment.value, "Status": f.status.value,
        "Origin": f.origin.value, "Source": "User-provided" if f.origin.value == "user_provided" else cite_label(f.source_pages),
        "Excerpt": f.excerpt or "", "Formula": f.formula or "",
        "Checks": "; ".join(([f.citation_check.value] if f.citation_check else []) + f.flags),
    } for f in ss.facts]
    edited = st.data_editor(
        rows, key="facts_editor", width="stretch", hide_index=True,
        disabled=[c for c in rows[0] if c not in ("Value", "Unit", "Period")] if rows else True,
    )
    if st.button("Apply fact corrections"):
        changed = 0
        for i, (old, new) in enumerate(zip(rows, edited)):
            if (old["Value"], old["Unit"], old["Period"]) != (new["Value"], new["Unit"], new["Period"]):
                ss.facts[i] = apply_user_correction(ss.facts[i], new["Value"], new["Unit"], new["Period"])
                changed += 1
        mark_conflicts(ss.facts, label)
        st.success(f"Applied {changed} correction(s), labelled as user-provided.")
        st.rerun()

with tab_pitch:
    timing = pitch_timing(result.pitch_script, int(wpm))
    st.write(result.pitch_script)
    c1, c2 = st.columns(2)
    c1.metric("Word count", timing.word_count, help=f"Target {PITCH_MIN_WORDS}–{PITCH_MAX_WORDS} words")
    c2.metric("Estimated duration", f"{timing.seconds:.0f} s", help=f"At {wpm} words per minute")
    st.caption(f"Duration is an estimate at {wpm} words per minute; actual delivery varies with pace, pauses "
               "and emphasis. Adjust the speaking rate in the sidebar.")
    if not timing.within_target_words:
        st.warning(f"The script is outside the {PITCH_MIN_WORDS}–{PITCH_MAX_WORDS} word target, usually because "
                   "the deck lacks enough supported facts. See information gaps.")

with tab_gaps:
    st.subheader("Information gaps")
    for gap in result.information_gaps or ["None identified."]:
        st.write(f"- {gap}")
    st.subheader("Extraction limitations and their effect on the evaluation")
    for lim in result.extraction_limitations or []:
        st.write(f"- **{cite_label(lim.pages)}:** {lim.limitation} _Effect:_ {lim.effect_on_evaluation}")
    if not result.extraction_limitations:
        st.write("No material extraction limitations.")
    if result.visual_observations:
        st.subheader("Read from slide/page images")
        for v in result.visual_observations:
            st.write(f"- {label.capitalize()} {v.page}: {v.observation}")

# ------------------------------------------------------------------ 5. one-pager

st.header("5 · Investor one-pager")
st.caption("Investor-facing: contains no scores or critique. Edit any field before export. Edited fields are "
           "recorded as user-provided in the analysis data.")
op: LLMOnePager = ss.onepager
orig: LLMOnePager = ss.onepager_orig

with st.form("onepager_form"):
    c1, c2 = st.columns(2)
    name = c1.text_input("Company name", op.company_name)
    website = c2.text_input("Website", op.website)
    values: dict[str, str] = {}
    for f in SECTION_FIELDS:
        sec: OnePagerSection = getattr(op, f)
        values[f] = st.text_area(f"{SECTION_LABELS[f]}  ·  {cite_label(sec.citations)}", sec.text,
                                 height=68 if f in ("positioning", "terms", "fundraising_target", "milestones",
                                                     "use_of_funds", "contact") else 110)
    st.write("Team")
    team_rows = st.data_editor(
        [{"Name": m.name, "Role": m.role, "Qualifications": m.qualifications} for m in op.team],
        num_rows="dynamic", width="stretch", key="team_editor",
    )
    keep_cites = st.checkbox("My edits only rephrase deck content — keep the original deck citations",
                             value=False)
    submitted = st.form_submit_button("Save one-pager edits")

if submitted:
    new = op.model_copy(deep=True)
    if name != op.company_name:
        new.company_name, ss.edits["company_name"] = name, "user_edited"
    if website != op.website:
        new.website, ss.edits["website"] = website.strip() or NOT_PROVIDED, "user_edited"
    for f, text in values.items():
        sec = getattr(new, f)
        if text.strip() != sec.text.strip():
            sec.text = text.strip() or NOT_PROVIDED
            if not keep_cites:
                sec.citations = []
            ss.edits[f] = "user_edited"
    old_team = [(m.name, m.role, m.qualifications) for m in op.team]
    new_team = [(r.get("Name") or "", r.get("Role") or "", r.get("Qualifications") or "") for r in team_rows]
    if new_team != old_team:
        members = []
        for row in new_team:
            if not row[0].strip():
                continue
            match = next((m for m in op.team if (m.name, m.role, m.qualifications) == row), None)
            members.append(match or TeamMember(name=row[0], role=row[1], qualifications=row[2], citations=[]))
        new.team = members
        ss.edits["team"] = "user_edited"
    ss.onepager = new
    st.rerun()

op = ss.onepager
pdf_bytes, fit = render_onepager(op, "p" if label == "page" else "S")
if fit.fits:
    st.success(f"Fits on one US Letter page at {fit.body_size:g} pt body text.")
    page_png = pymupdf.open(stream=pdf_bytes, filetype="pdf")[0].get_pixmap(dpi=110).tobytes("png")
    st.image(page_png, caption="Preview", width=760)
else:
    st.error(fit.message)
    st.write("Shorten the sections above, or let the app remove trailing sentences from lower-priority "
             "sections (whole sentences only; recorded as edits):")
    if st.button("Auto-shorten to fit"):
        shorter, changes, rep = shorten_to_fit(op, "p" if label == "page" else "S")
        ss.onepager = shorter
        ss.shorten_log += changes
        for f in SECTION_FIELDS:
            if getattr(shorter, f).text != getattr(op, f).text:
                ss.edits.setdefault(f, "auto_shortened")
        if not rep.fits:
            st.warning("Auto-shorten could not make the content fit; please shorten the named sections.")
        st.rerun()

user_texts = [getattr(op, f).text for f in ss.edits if f in SECTION_FIELDS and ss.edits[f] == "user_edited"]
for wmsg in onepager_figure_warnings(op, deck, ss.facts, user_texts):
    st.warning(wmsg)
if ss.shorten_log:
    with st.expander("Auto-shorten log"):
        for line in ss.shorten_log:
            st.write(f"- {line}")

# ------------------------------------------------------------------ 6. downloads

st.header("6 · Download")
final = result.model_copy(update={
    "facts": ss.facts,
    "onepager": op,
    "onepager_edits": dict(ss.edits),
    "timing": pitch_timing(result.pitch_script, int(wpm)),
})
stem = Path(deck.filename).stem
d1, d2, d3 = st.columns(3)
d1.download_button("Investor one-pager (PDF)", pdf_bytes or b"", file_name=f"{stem}_onepager.pdf",
                   mime="application/pdf", disabled=not fit.fits, width="stretch")
try:
    report_pdf = render_report(final)
except TemplateError as exc:
    report_pdf = None
    st.error(f"The analysis report template is invalid, so the report cannot be generated: {exc}")
d2.download_button("Analysis report (PDF, internal)", report_pdf or b"", file_name=f"{stem}_analysis_report.pdf",
                   mime="application/pdf", disabled=report_pdf is None, width="stretch")
d3.download_button("Structured data (JSON)", export_json(final), file_name=f"{stem}_analysis.json",
                   mime="application/json", width="stretch")

if settings.email_enabled:
    st.caption("Edited the facts or one-pager since the analysis? Email the current version as well.")
    if st.button(f"Email current version to {settings.report_email_to}"):
        with st.spinner("Sending…"):
            outcome = email_results(final, deck)
        (st.success if outcome.sent else st.error)(outcome.detail)

st.markdown(theme.FOOTER_HTML, unsafe_allow_html=True)
