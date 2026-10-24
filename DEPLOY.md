# Deploying to Railway

The app ships as a Docker image. Railway detects the `Dockerfile` (configured in
`railway.json`) and builds it. The image includes:

- LibreOffice, for legacy `.ppt` files and for rendering slides as images;
- the system libraries the local OCR engine needs.

The health check is Streamlit's `/_stcore/health`.

## 1. Get an API key

Create a key in the Anthropic Console (platform.claude.com → API keys). A Claude Code or
claude.ai subscription does not provide API access; this app is billed per request to the key's
organisation.

## 2. Create the service

From this folder:

```bash
railway login          # opens a browser
railway init           # new project (or `railway link` for an existing one)
```

## 3. Set variables (in Railway, never in a committed file)

| Variable | Required | Value |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes | your Console key |
| `APP_PASSWORD` | **strongly recommended** | sign-in password. Without it, anyone with the URL can run paid analyses on your key. The app shows a red warning when deployed without it. |
| `APP_USERNAME` | no | defaults to `ten` |
| `PITCH90_MODEL` | no | `claude-opus-5-5` |
| `PITCH90_EFFORT` | no | `high` |
| `PITCH90_MAX_CONCURRENT` | no | `2`: maximum simultaneous paid analyses across all users |
| `PITCH90_MAX_UPLOAD_MB` | no | `50` (Streamlit's own cap is set in `.streamlit/config.toml`) |
| `PITCH90_REPORT_TEMPLATE` | no | path inside the image to a custom report template |
| `RESEND_API_KEY` | for email | Resend API key. When set, every analysis is emailed with a summary, the one-pager PDF, the report PDF and the JSON. |
| `REPORT_EMAIL_TO` | no | `Info@tencapital.group` (comma-separate for several) |
| `REPORT_EMAIL_FROM` | no | `TEN Capital Pitch Analysis <pitch90@tencapital.group>`. **Must be on a domain verified in Resend**, otherwise Resend rejects the send and the app shows its reason. |
| `EMAIL_DEMO_RUNS` | no | `false`: demo runs on the synthetic sample deck are not emailed |

You can set them in the dashboard (service → Variables) or from the CLI:

```bash
railway variables --set "ANTHROPIC_API_KEY=sk-ant-..." --set "APP_PASSWORD=choose-a-strong-one" \
                   --set "RESEND_API_KEY=re_..."
```

## 4. Deploy

```bash
railway up             # uploads this folder, builds the Dockerfile, deploys
railway domain         # creates the public https://<name>.up.railway.app URL
railway logs           # build and runtime logs
```

The first build takes several minutes because of LibreOffice. Later builds reuse cached layers
unless `requirements.txt` or the Dockerfile changes.

## 5. Verify

1. `curl https://<your-domain>/_stcore/health` returns `ok`.
2. Open the URL and sign in. The sidebar should show **API key configured**, **Local OCR
   available** and **LibreOffice found**.
3. Click **Test API connection**. It checks the key and model with a free Models API lookup and
   uses no tokens.
4. Upload a deck, tick the consent box and click **Run analysis**. Then download the one-pager,
   the report (built from `templates/analysis_report.md`) and the JSON.
5. With `RESEND_API_KEY` set, a green "Results emailed to Info@tencapital.group" banner appears
   above the findings and the email arrives with the three attachments. If Resend refuses the
   send (for example an unverified sender domain), a yellow banner quotes Resend's reason. The
   analysis itself is never affected. **Email current version** re-sends after you edit facts or
   the one-pager.

## Operational notes

- **Cost.** Each analysis is one Messages API call: the deck text plus up to
  `PITCH90_MAX_VISUAL_PAGES` slide images in, up to about 32K tokens out. Typical decks cost
  well under a dollar on Claude Opus 5.5 at `high` effort. Use `PITCH90_MAX_CONCURRENT` and
  `APP_PASSWORD` to control spend.
- **Nothing is stored server-side.** Uploads are processed in temporary directories that are
  deleted afterwards. Results live in the browser session until downloaded, and a redeploy or
  closed tab discards them.
- **Long runs.** An analysis can take a few minutes. Streamlit keeps a websocket open, so no
  HTTP request timeout applies. Don't close the tab while the spinner runs.
- **Memory.** LibreOffice plus OCR fit comfortably in 1 GB. Very large image-heavy decks use more
  during rendering.
- **Email content.** Results emails contain AI analysis of the uploaded deck. Send them only to
  internal addresses.
- **Rotate the key** if it is ever pasted into chat, an issue or a commit. Logs never contain
  the key or the deck text.
