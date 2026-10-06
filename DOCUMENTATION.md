# JobPilot

JobPilot finds jobs, ranks them against your profile, writes a tailored cover letter, and fills in
the application form for you. By default it stops before submitting, so you can review a screenshot of
the filled form and approve it.

```text
Browser UI ──► Go gateway (:8090) ──► Python AI service (:8000) ──► SearXNG, Remotive, Arbeitnow
                serves frontend/       FastAPI + LangGraph             Groq LLM
                proxies /api/*         SQLite / PostgreSQL             Playwright Chromium
```

## Quick start (Windows, local)

Prerequisites: Python 3.11+, Go 1.22+, and a SearXNG instance with JSON output enabled.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
copy .env.example .env        # then set GROQ_API_KEY and SEARXNG_URL
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

Then open **http://localhost:8090**. You can also run only the AI service, which serves the same UI at
http://localhost:8000. Its API docs are at http://localhost:8000/docs.

### SearXNG

The AI service calls `GET /search?format=json`, and SearXNG disables JSON output by default (you get
HTTP 403). Use [searxng/settings.yml](searxng/settings.yml), or add the following to your own
`settings.yml`:

```yaml
server:
  limiter: false
search:
  formats: [html, json]
```

Search engines rate-limit repeated queries ("too many requests", "CAPTCHA"). When that happens, the
search response lists the unavailable engines in `errors`, and the UI shows them under the search box.
Suspensions clear on their own after a few minutes. Enabling more engines (bing, startpage, mojeek)
makes searches more resilient.

## Using it

1. **Profile**: upload your resume (PDF/DOCX/TXT). It is parsed with regexes plus Groq structured
   extraction. Review the fields, set target roles, locations, work arrangement and sponsorship need,
   then save. Saving re-scores all stored jobs.
2. **Discover**: search. Queries are expanded by the LLM and targeted at ATS sites (Greenhouse, Lever,
   Ashby, Workable). Every result is normalised, de-duplicated, scored, and stored.
3. **Prepare application**: the agent writes a cover letter and fills the form in headless Chromium.
   The application then appears in **Applications** as *Pending approval*, with a screenshot, the list
   of filled fields, and any required questions it could not answer.
4. **Approve & submit**: the agent re-opens the form, fills it with your (possibly edited) letter, and
   submits. It is marked *Applied* only after a confirmation message is detected.

**Auto-apply** does steps 3 and 4 without the review, but only when every required field is filled and
there is no visible CAPTCHA. Otherwise the application is handed back to you as *Needs manual*.

### What the agent will not do

- **Invent data.** Unknown fields stay empty, and the cover letter prompt forbids made-up facts.
- **Bypass CAPTCHAs or log in for you.** Those cases become *Needs manual*.
- **Answer screening questions** other than visa sponsorship, which it answers from your profile.
- **Claim success it did not observe.** If a submit click shows no confirmation, the status is
  *Needs manual* and you are told to check the screenshot before retrying.

## Matching score

| Signal | Weight | How it is computed |
|---|---|---|
| Title | 25% | Coverage of your target role's meaningful words (AI/ML/LLM treated as one family), ignoring generic words like "senior" or "engineer" |
| Skills | 35% | Overlap with skills found in the posting, shrunk toward neutral when the posting lists very few |
| Experience | 15% | Your years vs. the "N+ years" requirement |
| Location | 15% | Remote and region restrictions, preferred locations, relocation |
| Sponsorship | 10% | Explicit evidence only. A posting that says "no sponsorship" fails the hard filter when you need it |

An irrelevant title dampens the whole score. A job that fails a hard filter is capped at 35%.
Expand "Why this score" on any job card to see the reasons.

## API (prefix `/api/v1`)

| Method & path | Purpose |
|---|---|
| `GET /health` | Component status. Through the gateway it also includes gateway and upstream status |
| `POST /search` | `{roles, locations, remote_only, sponsorship_required, max_results}` → ranked jobs (persisted) |
| `GET /jobs` · `POST /jobs/rescore` · `DELETE /jobs` | Stored jobs |
| `GET/PUT /candidates/me` · `POST /candidates/me/resume` | Profile and resume upload |
| `GET /applications` · `POST /applications` | List; create `{job_id, auto_submit}` (202, runs in background) |
| `GET/PATCH /applications/{id}` | Read; edit `cover_letter` or set outcome `APPLIED/INTERVIEW/REJECTED/DISMISSED` |
| `POST /applications/{id}/approve` | Fill and submit (202) |
| `GET /applications/{id}/screenshot` | PNG of the last form state |

Application statuses: `PROCESSING → PENDING_APPROVAL → SUBMITTING → APPLIED`, or `NEEDS_MANUAL` / `FAILED`.

## Project layout

```text
ai_service/app/
  main.py                    FastAPI app, error mapping, startup recovery
  core/                      settings (.env), logging, domain errors
  api/deps.py, api/routes/   dependency wiring; health, search, jobs, candidates, applications
  agents/search_agent/       LangGraph: plan queries → search → normalise/filter → rank
  agents/application_agent/  LangGraph: prepare cover letter → fill / submit form
  integrations/              Groq client, SearXNG client, Playwright form filler
  services/                  search, normalisation, ATS detection, dedupe, skills catalogue,
                             visa evidence, matching, resume parsing, tailoring, applications, webhooks
  models/ schemas/ repositories/   SQLAlchemy models, Pydantic contracts, data access
  workers/                   periodic discovery CLI, employer email classifier
ai_service/tests/            pytest suite, including real-Chromium tests against a local fixture site
backend/                     Go gateway: cmd/server, internal/config, internal/server (+ tests)
frontend/                    static UI (ES modules, no build step)
docker/, docker-compose.yml  containers: gateway, ai_service, postgres, searxng
```

## Development

```powershell
.venv\Scripts\python -m pytest            # Python tests (includes headless browser tests)
.venv\Scripts\python -m ruff check ai_service; .venv\Scripts\python -m ruff format ai_service
cd backend; go vet ./...; go test ./...
```

Periodic discovery, which uses your profile's preferred roles and locations:

```powershell
.venv\Scripts\python -m ai_service.app.workers.job_worker --once
.venv\Scripts\python -m ai_service.app.workers.job_worker --interval 3600
```

## Docker

```bash
docker compose up --build      # UI on http://localhost:8090, SearXNG on :8081
```

Compose uses PostgreSQL and its own SearXNG, mounted with `searxng/settings.yml`. Set `SEARXNG_SECRET`
in your environment.

## Configuration

All settings are environment variables (see [.env.example](.env.example)). The most useful ones:
`GROQ_API_KEY`, `SEARXNG_URL`, `DATABASE_URL`, `BROWSER_HEADLESS` (set it to `false` to watch the
agent fill forms), `BROWSER_MAX_CONCURRENCY`, `NOTIFICATION_WEBHOOK_URL` and `HIGH_MATCH_THRESHOLD`.
The gateway reads `PORT` (default 8090), `AI_SERVICE_URL` and `CORS_ORIGINS`.

Data such as the SQLite database, uploaded resumes and screenshots lives in `./data`, which git ignores.
