"""TEN Capital look for the Streamlit app.

Colors, fonts and radii are set natively in .streamlit/config.toml; this module adds the
pieces Streamlit cannot theme: the ambient tri-color glow, the hero card around the
uploader, the gradient call-to-action, the step tracker and the brand lockup. Accent hex
values are the official TEN Capital logo colors. The logo is the official file shown on a
light chip, because its wordmark is black.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from html import escape

from pitch90.config import ASSETS_DIR

NAVY_950, NAVY_900, NAVY_800, NAVY_700 = "#0B1526", "#101E33", "#16283F", "#1E354F"
CORAL, CORAL_SOFT, AMBER, TEAL = "#ED5644", "#F0776C", "#F1A31F", "#4FC4D6"
INK_100, INK_300, INK_500 = "#F3F6FA", "#C4D0E0", "#8A9BB2"

CSS = f"""
<style>
:root {{
  --navy-950:{NAVY_950}; --navy-900:{NAVY_900}; --navy-800:{NAVY_800}; --navy-700:{NAVY_700};
  --coral:{CORAL}; --coral-soft:{CORAL_SOFT}; --amber:{AMBER}; --teal:{TEAL};
  --ink-100:{INK_100}; --ink-300:{INK_300}; --ink-500:{INK_500};
}}

/* ambient tri-color glow, echoing the logo's three figures */
[data-testid="stAppViewContainer"]::before {{
  content:""; position:fixed; inset:0; pointer-events:none; z-index:0;
  background:
    radial-gradient(480px 380px at 14% 8%, rgba(237,86,68,0.16), transparent 60%),
    radial-gradient(480px 380px at 86% 6%, rgba(241,163,31,0.13), transparent 60%),
    radial-gradient(560px 420px at 50% 100%, rgba(79,196,214,0.12), transparent 60%);
}}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stMainBlockContainer"] {{ max-width: 1120px; padding-top: 2.5rem; }}

/* brand lockup */
.ten-brand {{ display:flex; align-items:center; justify-content:space-between; gap:12px; margin: 0 auto 22px; max-width:620px; }}
.ten-logo-chip {{ background:#FFFFFF; border-radius:10px; padding:7px 12px; display:inline-flex; line-height:0;
  box-shadow: 0 6px 18px -10px rgba(0,0,0,0.6); }}
.ten-logo-chip img {{ height:30px; width:auto; }}
.ten-brand-tag {{ font-family:'JetBrains Mono',monospace; font-size:11px; letter-spacing:.14em;
  text-transform:uppercase; color:var(--ink-500); }}

/* hero card: a keyed Streamlit container, so real widgets sit inside it */
.st-key-hero {{
  max-width:620px; margin:0 auto; position:relative; overflow:hidden;
  background: linear-gradient(180deg, var(--navy-900) 0%, var(--navy-800) 100%);
  border:1px solid var(--navy-700) !important; border-radius:20px !important;
  padding: 36px 40px 28px !important;
  box-shadow: 0 30px 60px -20px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.03);
}}
.st-key-hero::after {{
  content:""; position:absolute; top:0; left:40px; right:40px; height:2px; border-radius:2px;
  background: linear-gradient(90deg, var(--coral), var(--amber), var(--teal));
}}
.st-key-signin {{ max-width:420px; margin: 0 auto; }}
.ten-eyebrow {{ display:flex; align-items:center; gap:8px; font-family:'JetBrains Mono',monospace;
  font-size:11px; letter-spacing:.14em; text-transform:uppercase; color:var(--teal); margin-bottom:12px; }}
.ten-eyebrow::before {{ content:""; width:6px; height:6px; border-radius:50%; background:var(--teal);
  box-shadow:0 0 0 3px rgba(79,196,214,0.18); }}
.ten-h1 {{ font-family:'Sora',sans-serif; font-size:28px; font-weight:700; line-height:1.25;
  margin:0 0 10px; letter-spacing:-0.01em; color:var(--ink-100); }}
.ten-h1 .arrow {{ color:var(--ink-500); font-weight:400; margin:0 4px; }}
.ten-h1 .to {{ background:linear-gradient(90deg, var(--coral-soft), var(--amber));
  -webkit-background-clip:text; background-clip:text; color:transparent; }}
.ten-lede {{ color:var(--ink-300); font-size:15px; line-height:1.6; margin:0 0 6px; max-width:48ch; }}

/* dropzone */
[data-testid="stFileUploaderDropzone"] {{
  border:1.5px dashed var(--navy-700); border-radius:14px; background:rgba(255,255,255,0.015);
  padding: 28px 20px; transition: border-color .18s ease, background .18s ease;
}}
[data-testid="stFileUploaderDropzone"]:hover {{ border-color:var(--teal); background:rgba(79,196,214,0.05); }}

/* gradient call-to-action for primary buttons */
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {{
  background: linear-gradient(90deg, var(--coral) 0%, var(--coral-soft) 45%, var(--amber) 100%) !important;
  color:#17130E !important; border:none !important; font-family:'Sora',sans-serif; font-weight:700;
  box-shadow: 0 10px 24px -10px rgba(237,86,68,0.45); transition: filter .15s ease, transform .15s ease;
}}
[data-testid="stBaseButton-primary"] p, [data-testid="stBaseButton-primaryFormSubmit"] p {{ font-weight:700; color:#17130E; }}
[data-testid="stBaseButton-primary"]:hover:not(:disabled) {{ filter:brightness(1.06); transform:translateY(-1px); }}
[data-testid="stBaseButton-primary"]:disabled {{ filter:grayscale(0.7) brightness(0.7); box-shadow:none; }}
button:focus-visible {{ outline: 2px solid var(--teal) !important; outline-offset: 2px; }}

/* disclosure + footer */
.ten-disclosure {{ margin-top:14px; padding-top:14px; border-top:1px solid var(--navy-700);
  font-size:12px; line-height:1.6; color:var(--ink-500); }}
.ten-disclosure code {{ font-family:'JetBrains Mono',monospace; background:var(--navy-950);
  border:1px solid var(--navy-700); color:var(--ink-300); padding:2px 6px; border-radius:5px; font-size:11.5px; }}
.ten-footer {{ text-align:center; margin:40px 0 8px; font-family:'JetBrains Mono',monospace;
  font-size:11px; letter-spacing:.08em; color:var(--ink-500); text-transform:uppercase; }}

/* step tracker */
.ten-steps {{ display:flex !important; flex-direction:row; gap:6px; flex-wrap:wrap; justify-content:center;
  margin: 22px auto 6px; max-width: 900px; }}
.ten-step {{ font-family:'JetBrains Mono',monospace; font-size:11px; letter-spacing:.06em; text-transform:uppercase;
  padding:6px 10px; border-radius:999px; border:1px solid var(--navy-700); color:var(--ink-500); background:var(--navy-900);
  white-space:nowrap; }}
.ten-step.done {{ color:var(--ink-100); border-color:rgba(79,196,214,0.45); }}
.ten-step.done::before {{ content:"\\2713  "; color:var(--teal); }}
.ten-step.current {{ color:#17130E; border-color:transparent;
  background:linear-gradient(90deg, var(--coral-soft), var(--amber)); font-weight:500; }}

/* section headings, metrics, expanders */
h2 {{ letter-spacing:-0.01em; }}
[data-testid="stMetric"] {{ background:var(--navy-900); border:1px solid var(--navy-700); border-radius:14px; padding:14px 18px; }}
[data-testid="stMetricValue"] {{ font-family:'Sora',sans-serif; font-weight:700; color:var(--amber); }}
[data-testid="stExpander"] details {{ border-color:var(--navy-700); border-radius:12px; }}

@media (max-width: 640px) {{
  .st-key-hero {{ padding: 28px 22px 22px !important; }}
  .ten-h1 {{ font-size:23px; }}
}}
@media (prefers-reduced-motion: reduce) {{
  * {{ transition:none !important; }}
}}
</style>
"""

STEPS = ["Upload", "Review", "Analyse", "Findings", "One-pager", "Download"]


@lru_cache(maxsize=1)
def logo_data_uri() -> str:
    data = (ASSETS_DIR / "ten_capital_logo.png").read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def brand_html(tag: str = "Deck Analyzer") -> str:
    return (
        '<div class="ten-brand">'
        f'<span class="ten-logo-chip"><img src="{logo_data_uri()}" alt="TEN Capital Network"></span>'
        f'<span class="ten-brand-tag">{escape(tag)}</span></div>'
    )


def hero_html() -> str:
    return (
        '<div class="ten-eyebrow">90-Second Pitch Test</div>'
        '<div class="ten-h1">Pitch Deck<span class="arrow">&rarr;</span>'
        '<span class="to">Investor One&#8209;Pager</span></div>'
        '<p class="ten-lede">Upload a pitch deck to test whether it tells its story in 90 seconds, '
        'then get a polished single-page investor PDF, analyzed and structured by Claude.</p>'
    )


def disclosure_html(types: str, max_mb: int, recipient: str | None) -> str:
    text = (f"Accepts <b>{escape(types)}</b> up to {max_mb}&nbsp;MB. The deck is processed on the server; "
            "clicking <i>Run analysis</i> sends its text and selected slide images to Anthropic's API.")
    if recipient:
        text += f" A copy of every analysis is emailed to <code>{escape(recipient)}</code>."
    return f'<div class="ten-disclosure">{text}</div>'


def steps_html(done: int) -> str:
    """Step tracker; ``done`` is the number of completed steps (the next one is current)."""
    items = []
    for i, name in enumerate(STEPS):
        cls = "done" if i < done else "current" if i == done else ""
        aria = ' aria-current="step"' if i == done else ""
        items.append(f'<span class="ten-step {cls}" role="listitem"{aria}>{i + 1} · {escape(name)}</span>')
    return f'<div class="ten-steps" role="list" aria-label="Progress">{"".join(items)}</div>'


FOOTER_HTML = '<div class="ten-footer">Powered by TEN Capital Network</div>'
