# JobPilot

JobPilot finds jobs, ranks them against your profile, writes a tailored cover letter, and fills in
the application form for you. By default it stops before submitting, so you can review a screenshot of
the filled form and approve it.

```text
Browser UI ──► Go gateway (:8090) ──► Python AI service (:8000) ──► SearXNG, Remotive, Arbeitnow, ATS APIs
                serves frontend/       FastAPI + LangGraph             Groq LLM
                checks API_TOKEN       SQLite / PostgreSQL (Alembic)   Playwright Chromium
                proxies /api/*         background task queue
```

## Quick start (Windows, local)

Prerequisites: Python 3.11+, Go 1.22+, and a SearXNG instance with JSON output enabled.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
copy .env.example .env        # then set GROQ_API_KEY and SEARXNG_URL (and API_TOKEN, see Security)
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

Then open **http://localhost:8090**. You can also run only the AI service, which serves the same UI at
http://localhost:8000. Its API docs are at http://localhost:8000/docs.

The database schema is created and upgraded automatically on startup. A database created by an older
version is upgraded in place, and its data is kept.

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
   extraction. Review the fields, then set target roles, locations, work arrangement, sponsorship need,
   and optionally your expected salary and notice period (used only to answer those form questions).
   Saving re-scores all stored jobs.
2. **Discover**: search. Queries are expanded by the LLM and sent to every job source (see
   [Where jobs come from](#where-jobs-come-from)). Progress is shown live, stage by stage. Every result is
   normalised, de-duplicated, verified with the job board where possible, scored, and stored. Stored jobs
   are re-checked every 12 hours, and postings that have closed are hidden. On any job card,
   **Not interested** (eye icon) hides it for good, and **Hide company** (ban icon) hides every job from
   that company; both can be undone (Profile → Hidden companies).
3. **Prepare application**: the agent writes a cover letter and fills the form in headless Chromium.
   The application then appears in **Applications** as *Pending approval*, with screenshots, the list
   of filled fields, the questions it could not answer, and an **Agent activity** timeline of every step.
4. **Answer open questions**: for required questions the agent could not answer, it drafts an answer
   from your profile (marked as an AI draft). Correct it if needed, then **Save answers & re-fill**.
   Saved answers go to your **answer bank** (Profile tab) and are reused on every later form that asks
   the same question.
5. **Approve & submit**: the agent re-opens the form, fills it with your (possibly edited) letter, and
   submits. It is marked *Applied* only after a confirmation message is detected.

**Auto-apply** does steps 3 and 5 without the review, but only when every required field is filled and
there is no visible CAPTCHA. Otherwise the application is handed back to you as *Needs manual*.

**Tailored resume** (Profile → "Attach a resume tailored to each job"): the agent builds a PDF from your
profile that leads with the skills the posting asks for, and attaches it instead of your uploaded file.
Bullets are copied verbatim from your experience and only reordered; nothing is rewritten or added.
Each application also shows which of the posting's skills your profile covers and which it lacks, and
the tailored PDF can be downloaded from the application.

Forms can be filled on Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, Teamtailor,
BambooHR and Personio. Other sites, including LinkedIn, Indeed, Naukri and Workday, are *Apply manually*:
JobPilot opens the site, drafts a letter to paste, and asks afterwards whether you applied.

### Where jobs come from

Everything is open source and uses only public, documented interfaces or your own email. LinkedIn,
Indeed and Naukri are never scraped or logged into.

| Source | How | Applying |
|---|---|---|
| **Company job boards** | Public job APIs of Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee and Personio: a built-in list, boards seen in search results, and your **watchlist** (System tab → paste any job or careers link) | Auto-fill |
| **Web search** (SearXNG) | ATS-targeted queries, plus `site:` queries for LinkedIn, Naukri and Indeed job pages (`SEARCH_JOB_SITES`) | Auto-fill on ATS sites; manual on job sites |
| **Job-alert emails** | Set up alerts on LinkedIn, Indeed and Naukri; JobPilot reads those emails from your inbox (read-only IMAP) and adds the jobs | Manual |
| **Remotive, Arbeitnow** | Their public APIs | Manual |

**Job-alert inbox** (System tab): put `IMAP_USER` and `IMAP_PASSWORD` in `.env` (for Gmail, an *app
password*: turn on 2-step verification, then Google Account → Security → App passwords) and restart. The
inbox is checked every 30 minutes, or with **Check now**. It is opened read-only, so nothing is marked as
read. Only alert emails and emails naming a company you applied to are downloaded; nothing about other
emails is stored. Tracking links in alerts are followed (one request each, like a click) to find the job
URL; set `INBOX_RESOLVE_TRACKING_LINKS=false` to skip that.

The same check reads **replies from companies**. "We received your application", interview invitations
and rejections move the application forward (*Applied*, *Interview*, *Rejected*) and are added to its
activity timeline. To avoid mistakes, the company must appear in the email's sender or subject, exactly
one of your applications must match, and a status never moves backwards. Set `INBOX_UPDATE_STATUSES=false`
to turn this off.

**Scheduled discovery**: set `DISCOVERY_INTERVAL_HOURS` (for example `6`) and your profile's search runs
on its own; strong matches are sent to your webhook if one is set.

### What the agent will not do

- **Invent data.** Unknown fields stay empty, and the cover letter prompt forbids made-up facts.
- **Use an answer you have not approved.** Forms are filled only from your profile and your answer bank.
  AI-drafted answers are suggestions shown to you; they are used only after you save them. The only
  automatic answers are "decline to answer" for voluntary demographic questions, your sponsorship need,
  and "Yes" to relocation if your profile says you are willing to relocate.
- **Guess between similar questions.** Saved answers match the question's exact wording (ignoring case,
  punctuation and "required" markers), so "authorized to work in the US?" never answers "...in the UK?".
- **Bypass CAPTCHAs or log in for you.** Those cases become *Needs manual*.
- **Claim success it did not observe.** If a submit click shows no confirmation, the status is
  *Needs manual* and you are told to check the screenshot before retrying.
- **Submit twice.** A failed fill is retried automatically (up to `TASK_MAX_ATTEMPTS`), but never once
  the submit button was clicked. If the service stops in the middle of submitting, the application is
  handed back to you instead of being retried.

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

Every endpoint except `/health` requires the API token when `API_TOKEN` is set
(`Authorization: Bearer <token>` or `X-API-Token: <token>`).

| Method & path | Purpose |
|---|---|
| `GET /health` | Component status (database, SearXNG, LLM, Chromium). Through the gateway it also includes gateway and upstream status |
| `POST /search` | `{roles, locations, remote_only, sponsorship_required, strict_location, max_results}` → ranked jobs (persisted) |
| `POST /search/stream` | Same, as Server-Sent Events: `stage` events (`{stage, label, detail}`), then `result` (or `error`) |
| `GET /jobs?limit&include_closed&hidden` | Stored jobs, best match first; closed, hidden and blocked-company jobs left out (`hidden=true` lists the hidden ones) |
| `POST /jobs/{id}/hide` · `POST /jobs/{id}/unhide` | Not interested / undo |
| `POST /jobs/rescore` · `DELETE /jobs` | Re-score every stored job · delete jobs (those with an application are kept) |
| `POST /jobs/recheck?limit&force` | Ask the job boards which stored postings are still open |
| `GET /boards` · `POST /boards` · `DELETE /boards/{ats}/{slug}` | Company boards searched directly; `POST {url}` watches a company from any of its job links |
| `GET /inbox` · `POST /inbox/check` | Job-alert inbox status · read new alert emails and company replies now |
| `GET/PUT /candidates/me` · `POST /candidates/me/resume` | Profile and resume upload |
| `GET /applications` · `POST /applications` | List; create `{job_id, mode: review\|auto\|manual, tailor_resume?}` (202, queued) |
| `GET/PATCH /applications/{id}` | Read; edit `cover_letter` or set outcome `APPLIED/INTERVIEW/REJECTED/DISMISSED` |
| `POST /applications/{id}/approve` | Fill and submit (202, queued) |
| `POST /applications/{id}/refill` | Fill again without submitting, e.g. after answering its questions (202, queued) |
| `GET /applications/{id}/screenshot` | PNG of the latest form state |
| `GET /applications/{id}/screenshots/{name}` | A screenshot referenced by the activity timeline |
| `GET /applications/{id}/resume` | The tailored resume PDF attached to the application |
| `GET/PUT /screening-answers` · `DELETE /screening-answers/{id}` | The answer bank; `PUT [{question, answer}]` upserts by question, an empty answer removes it |

Application statuses: `PROCESSING → PENDING_APPROVAL → SUBMITTING → APPLIED`, or `NEEDS_MANUAL` / `FAILED`.
Applications also carry `events` (the activity timeline), `questions` (open required questions with
AI-drafted `suggestion`s), `resume_report` and `has_tailored_resume`.

## Security

- **Bind to localhost.** The gateway listens on `127.0.0.1` by default (`BIND_ADDR`), and the compose
  file publishes ports on `127.0.0.1` only. The AI service is not published by compose at all.
- **API token.** Set `API_TOKEN` in `.env` whenever anyone but you can reach the service. Both the gateway
  and the AI service check it. The UI asks for it once and keeps it in the browser's local storage.
- **CORS** allows only the local UI origins (`CORS_ORIGINS` to change).
- Resumes, tailored resumes and screenshots live in `./data`, which git ignores. They contain personal
  data; delete the folder to remove everything.

## Project layout

```text
ai_service/app/
  main.py                    FastAPI app, error mapping, startup recovery, background task runner
  core/                      settings (.env), logging, domain errors, API-token check, timeline entries
  api/deps.py, api/routes/   dependency wiring; health, search, jobs, candidates, applications, screening
  agents/search_agent/       LangGraph: plan queries → search → verify → normalise/filter → rank (streamable)
  agents/application_agent/  LangGraph: cover letter + tailored resume → fill / submit form
  integrations/              Groq client, SearXNG client; browser/: Playwright runtime, form filler, PDF renderer
  services/                  search, normalisation, ATS detection, dedupe, enrichment, job re-checks,
                             skills catalogue, visa evidence, matching, resume parsing and tailoring,
                             cover letters, screening answers, applications, task runner, webhooks
  models/ schemas/ repositories/   SQLAlchemy models, Pydantic contracts, data access
  integrations/mail/         read-only IMAP reader
  services/inbox/            job-alert parsing, employer-email classifier, status matching
  workers/                   periodic discovery CLI
ai_service/migrations/       Alembic migrations (run automatically on startup)
ai_service/tests/            pytest suite: unit, API, migrations, real-Chromium form filling, and UI tests
backend/                     Go gateway: cmd/server, internal/config, internal/server (+ tests)
frontend/                    static UI (ES modules, no build step)
docker/, docker-compose.yml  containers: gateway, ai_service, postgres, searxng
scripts/                     dev.ps1 (run locally), lock_deps.py (pin dependencies)
.github/workflows/ci.yml     lint and tests for Python, Go, the frontend, and the compose file
```

### Background work

Agent work (form fills, submits, cover-letter drafts) is stored in the `agent_tasks` table and run by
a worker loop inside the AI service, so it survives restarts. Tasks are claimed atomically, failed fills
are retried with backoff (`TASK_RETRY_BACKOFF_SECONDS`), and on startup interrupted fills are resumed
while interrupted submits are handed back to you. The same loop re-checks stored jobs periodically.

## Development

```powershell
.venv\Scripts\python -m pytest            # all Python tests (includes headless-browser and UI tests)
.venv\Scripts\python -m ruff check ai_service scripts; .venv\Scripts\python -m ruff format ai_service scripts
cd backend; go vet ./...; go test ./...
```

Changing a model? Create a migration, review it, and add it to the commit:

```powershell
.venv\Scripts\alembic revision --autogenerate -m "describe the change"
```

`ai_service/tests/test_migrations.py` fails if the migrations and the models drift apart.

Dependencies are pinned in `ai_service/constraints.txt`. After changing `ai_service/requirements.txt`,
install, test, and regenerate the pins with `.venv\Scripts\python scripts\lock_deps.py`.

Periodic discovery, which uses your profile's preferred roles and locations:

```powershell
.venv\Scripts\python -m ai_service.app.workers.job_worker --once
.venv\Scripts\python -m ai_service.app.workers.job_worker --interval 3600
```

## Docker

```bash
docker compose up --build      # UI on http://localhost:8090, SearXNG on :8081
```

Compose uses PostgreSQL and its own SearXNG, mounted with `searxng/settings.yml`. Set
`POSTGRES_PASSWORD` and `SEARXNG_SECRET` in `.env` (compose refuses to start without them), and
`API_TOKEN` if the machine is shared. The AI service container runs as an unprivileged user.

## Configuration

All settings are environment variables (see [.env.example](.env.example)). The most useful ones:

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | (none) | LLM for query expansion, resume extraction, cover letters, answer drafts |
| `SEARXNG_URL` | `http://localhost:8080` | Web search |
| `DATABASE_URL` | SQLite in `./data` | Any SQLAlchemy async URL (PostgreSQL in compose) |
| `API_TOKEN` | (empty: off) | Shared secret required on the API, checked by gateway and AI service |
| `BROWSER_HEADLESS` | `true` | Set `false` to watch the agent fill forms |
| `BROWSER_MAX_CONCURRENCY` | `2` | Simultaneous Chromium instances |
| `TASK_MAX_ATTEMPTS` | `3` | Attempts per form fill (submits are never retried after the click) |
| `TASK_CONCURRENCY` | `3` | Background tasks run at once |
| `JOB_RECHECK_INTERVAL_HOURS` | `12` | How often stored jobs are re-verified (`0` disables) |
| `SEARCH_JOB_SITES` | LinkedIn, Naukri, Indeed | Job sites added as `site:` web searches (`[]` disables) |
| `IMAP_USER`, `IMAP_PASSWORD` | (empty: off) | Job-alert inbox (Gmail: app password); also `IMAP_HOST`, `IMAP_FOLDER` |
| `INBOX_CHECK_INTERVAL_MINUTES` | `30` | How often the inbox is read (`0`: only with Check now) |
| `INBOX_UPDATE_STATUSES` | `true` | Move applications forward from company replies |
| `DISCOVERY_INTERVAL_HOURS` | `0` (off) | Run your profile's search automatically |
| `NOTIFICATION_WEBHOOK_URL`, `HIGH_MATCH_THRESHOLD` | (empty), `85` | Slack/Discord alerts for strong matches |

The gateway reads `BIND_ADDR` (default `127.0.0.1`), `PORT` (default 8090), `AI_SERVICE_URL`,
`CORS_ORIGINS` and `API_TOKEN`.

Data such as the SQLite database, uploaded and tailored resumes, and screenshots lives in `./data`,
which git ignores.
