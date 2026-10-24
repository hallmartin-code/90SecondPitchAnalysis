# 90-Second Pitch Test

A local Streamlit app that reads an investor pitch deck (PDF, PPTX or legacy PPT), tests
whether it tells a compelling company story in 90 seconds, and produces:

- an **investor-facing one-page PDF** (US Letter, two columns, cited to slides/pages);
- a separate **internal analysis report** (PDF) with scores, critique and an evidence register;
- **structured JSON** of the full analysis, including user corrections.

The narrative test follows Andy Raskin's
[*Your Pitch, 90 Seconds*](https://medium.com/firm-narrative/your-pitch-90-seconds-4b2c473c44b6).
A summary of its five elements is stored in [src/pitch90/framework.py](src/pitch90/framework.py), so
the app never fetches the article at runtime. The 0–5 rubric is this app's own adaptation and
does not come from the article. The app assesses how well the deck tells its story. It does not
assess investment merit.

## Install

Requires Python 3.11+.

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt  # runtime deps + pytest
copy .env.example .env           # macOS/Linux: cp .env.example .env
```

Put your Anthropic API key in `.env` (`ANTHROPIC_API_KEY=...`). Create the key at
platform.claude.com. A Claude Code or claude.ai subscription does **not** include API access
for this app. Without a key the app still runs in **demo mode**.

## Deploy as a web app

See [DEPLOY.md](DEPLOY.md) for Railway: Dockerfile build, `ANTHROPIC_API_KEY` and `APP_PASSWORD`
variables, and verification steps.

## Launch

```bash
streamlit run app.py
```

Then open http://localhost:8501. The workflow:

1. **Upload** a deck, or click *Load synthetic sample deck*.
2. **Review extraction.** Warnings appear first (OCR'd, image-only, hidden or unreadable
   slides/pages, embedded AI instructions). Then browse the content per slide, with speaker notes
   shown separately from visible content.
3. **Run the analysis.** API mode requires you to tick a consent box: deck text, notes and up to
   `PITCH90_MAX_VISUAL_PAGES` slide images are sent to Anthropic. Demo mode makes no network calls.
4. **Review findings.** You get the score out of 25 and a percentage, an assessment of each
   element, the three strongest points and three priority fixes, inconsistencies, gaps and
   extraction limitations, and a 180–210-word pitch with its duration at the configurable
   speaking rate. Correct facts in the evidence table; corrections are labelled
   `user_provided` and carry no slide citation.
5. **Edit the one-pager.** Edited fields are recorded as `user_edited` in the analysis data,
   and their deck citations are dropped unless you confirm the edit only rephrases deck content.
6. **Download** the one-pager PDF, the analysis report PDF and the JSON.

### Optional system dependencies

| Dependency | Needed for | Without it |
|---|---|---|
| LibreOffice (`soffice`) | `.ppt` conversion; rendering PPTX slides as images for visual interpretation | `.ppt` uploads are refused with install instructions; PPTX visual review falls back to the slide's largest embedded picture, and the limitation is reported |
| OCR | Installed with `rapidocr-onnxruntime` (pip); no system install | Image-only pages are flagged as unread |

LibreOffice is found automatically on PATH or in its default install location. To point at it
explicitly, set `PITCH90_SOFFICE_PATH`.

### Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | API access (never logged or displayed) |
| `PITCH90_MODEL` | `claude-opus-5-5` | Model for analysis |
| `PITCH90_EFFORT` | `high` | Reasoning effort |
| `PITCH90_FALLBACKS` | `default` | Server-side refusal fallback (`off` to disable) |
| `PITCH90_TIMEOUT_SECONDS` | `300` | Request timeout |
| `PITCH90_MAX_VISUAL_PAGES` | `12` | Slide/page images sent per analysis |
| `PITCH90_MAX_UPLOAD_MB` / `PITCH90_MAX_PAGES` | `50` / `150` | Upload limits (also set `server.maxUploadSize` in `.streamlit/config.toml`) |
| `PITCH90_WORDS_PER_MINUTE` | `140` | Default speaking rate |
| `PITCH90_REPORT_TEMPLATE` | `templates/analysis_report.md` | Analysis report structure template |
| `APP_USERNAME` / `APP_PASSWORD` | `ten` / – | Sign-in gate (enabled when a password is set) |
| `PITCH90_MAX_CONCURRENT` | `2` | Simultaneous paid analyses across all users |
| `RESEND_API_KEY` | – | Turns on result emails (summary + one-pager + report + JSON) |
| `REPORT_EMAIL_TO` / `REPORT_EMAIL_FROM` | `Info@tencapital.group` / `pitch90@tencapital.group` | Recipients (comma-separated) and sender; the sender must be on a domain verified in Resend |
| `EMAIL_DEMO_RUNS` | `false` | Also email demo-mode runs |

## Accuracy safeguards

- **Deck text is data, not instructions.** It is wrapped in delimiters that cannot be spoofed,
  and the system prompt tells the model to ignore embedded instructions. The app also scans for
  instruction-like text and warns you.
- **Every fact** records its value, unit, period, source slide/page, verbatim excerpt, basis
  (actual / forecast / target) and commitment (signed customer, pilot, LOI, prospect, capital
  raised / committed / sought). Its status is one of stated, calculated, inferred, missing or
  conflicting.
- **The app does not trust the model's citations.** Each cited excerpt is checked against the
  extracted text of the cited slide. Citations to slides that don't exist are removed.
  Calculated values are recomputed from their formula with a safe arithmetic evaluator.
- **Conflicting figures are flagged and never resolved silently.** This applies to facts with
  the same metric and basis whose periods are the same or undated.
- **Figures in the one-pager and pitch** that appear nowhere in the deck or the facts are flagged.
  An exit strategy or contact without a deck citation, or a website not found in the deck, is
  replaced with "Not provided".
- **Responses are schema-validated** with structured output plus Pydantic. An invalid response
  is retried once, then reported. Refusals, truncation, timeouts, rate limits, auth and network
  errors produce clear messages.
- Narrative scores are kept separate from extraction confidence. Deck citations show where a
  claim appears; they do not verify it.

## One-pager layout rules

The one-pager is exactly one US Letter page with embedded Carlito fonts (SIL OFL), body text of
at least 9 pt, a two-column layout, compact `[S#]` / `[p #]` citations and the footer
"Confidential – for recipients only." Exit strategy and contact appear only when the deck
supplies them.

Content is measured before it is drawn. The app tries every column split and steps the body
size from 10 to 9.5 to 9 pt. If the content still doesn't fit, nothing is rendered. Instead the
app names the sections to shorten, with approximate word cuts, and offers **Auto-shorten**. That
removes whole trailing sentences from lower-priority sections and logs each removal as an edit.
It never clips text, adds a page or goes below 9 pt.

## Analysis report template

The internal report's structure is defined in
[templates/analysis_report.md](templates/analysis_report.md). It holds only placeholders and
contains no company data. The template sets:

- section order and headings;
- the notes shown under each section;
- table columns and their relative widths;
- line formats;
- the text shown when a section is empty, and which sections are dropped when they have no data;
- the footer pattern.

`{{field}}` placeholders take document-level values. `{{item.field}}` lines repeat once per
item, such as each narrative element, fact or gap. The syntax and the full list of fields are
documented at the top of the file. `<!-- guide: ... -->` comments describe what each section
should contain and are not rendered.

To change the report for future decks, edit the template. To use a different one, set
`PITCH90_REPORT_TEMPLATE` to its path. Templates are validated on load: an unknown section,
an unknown field or a column-count mismatch raises a clear error. The investor one-pager keeps
its own fixed layout.

## Project layout

```
app.py                         Streamlit interface
src/pitch90/
  config.py                    settings from env/.env
  models.py                    Pydantic schemas (LLM output + domain)
  framework.py                 local Raskin summary and rubric
  ingest/validate.py           type/size/signature/encryption checks, safe names
  ingest/convert.py            LibreOffice discovery and conversion
  ingest/pdf.py, pptx.py       extraction with original numbering
  ingest/ocr.py                local OCR (RapidOCR)
  evidence.py                  citation, conflict, formula and figure checks
  llm.py                       Anthropic request, prompt, response validation
  mailer.py                    result emails via Resend (never fails an analysis)
  analysis.py                  turns a model response into a checked AnalysisResult
  scoring.py                   totals, percentage, pitch duration
  demo.py                      synthetic demo mode
  render/onepager.py           one-page PDF layout and fitting
  render/template.py           Markdown structure-template parser/validator
  render/report.py             template-driven internal report PDF + JSON export
templates/analysis_report.md   structure template for the analysis report
samples/                       synthetic deck (.pptx/.pdf), demo response, generated outputs
scripts/                       sample deck and sample output generators
tests/                         pytest suite
```

## Samples

`samples/tidewell_sample_deck.pptx` (and its `.pdf` export) is a **fictional** company deck
built to exercise the app. It contains a conflicting ARR figure (slides 6 and 12), an image-only
slide (7), a native chart (8), a table (5), speaker notes, a hidden slide (13) and an embedded
"ignore previous instructions" line in the notes of slide 12. The outputs it generates in demo
mode are in `samples/output/`. To regenerate:

```bash
python scripts/make_sample_deck.py        # deck (PDF export needs LibreOffice)
python scripts/generate_sample_outputs.py # one-pager, report, JSON, preview PNG
```

## Tests

```bash
python -m pytest
```

The suite covers PDF/PPTX extraction with preserved numbering, notes kept separate, OCR,
hidden-slide render mapping, corrupt, empty, encrypted, oversized and mislabelled uploads,
legacy PPT both with and without LibreOffice, and missing, conflicting, calculated, inferred and
user-corrected facts. It also covers score and duration maths, malformed, truncated and refused
model responses, API error mapping, delimiter spoofing, a one-page check with embedded fonts and
a 9 pt minimum, no-clipping checks with very long names and content, overflow refusal and
auto-shorten, the report and JSON export, and a headless run of the Streamlit demo workflow.
Tests that need LibreOffice or OCR are skipped when those are missing.
