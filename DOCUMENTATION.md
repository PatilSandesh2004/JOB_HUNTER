# JobPilot

JobPilot finds jobs, ranks them against your resume, writes a tailored cover letter, and fills in the
application form for you. By default it stops before submitting, so you can review a screenshot of the
filled form and approve it. It also tracks your applications from "saved" to "offer", reminds you to
follow up, and helps you prepare for interviews.

```text
Browser UI ──► Go gateway (:8090) ──► Python AI service (:8000) ──► company job boards, job feeds, SearXNG
                serves frontend/       FastAPI + LangGraph             Groq LLM (optional)
                checks API_TOKEN       SQLite / PostgreSQL (Alembic)   local embedding model (fastembed)
                proxies /api/*         background task queue           Playwright Chromium
```

## Quick start (Windows, local)

Prerequisites: Python 3.11+, Go 1.22+, and a SearXNG instance with JSON output enabled (see
[HOW_TO_RUN.md](HOW_TO_RUN.md) for every step).

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
copy .env.example .env        # then set GROQ_API_KEY and SEARXNG_URL (and API_TOKEN, see Security)
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

Then open **http://localhost:8090**. You can also run only the AI service, which serves the same UI at
http://localhost:8000. Its API docs are at http://localhost:8000/docs.

The database schema is created and upgraded automatically on startup; existing data is kept. On the first
start the resume-similarity model (about 65 MB) is downloaded into `data/models` in the background.

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
Suspensions clear on their own after a few minutes. Instead of SearXNG you can use Google results through
[Serper](https://serper.dev) (`WEB_SEARCH_PROVIDER=serper`, `SERPER_API_KEY=...`). Web search is only one
source: company job boards and job feeds work without it.

## Using it

1. **Profile**: upload your resume (PDF/DOCX/TXT). It is parsed with regexes plus Groq structured
   extraction, which also suggests up to four **target roles** you are a strong fit for (filled in only if
   you have not set any). Review the fields, then set locations, work arrangement, sponsorship need, and
   optionally expected salary and notice period. Saving re-scores all stored jobs.
2. **Search**: type roles and locations, or leave the role empty to search from your resume. Progress is
   shown live, stage by stage (see [How search works](#how-search-works)). Every result is normalised,
   de-duplicated, verified with the job board where possible, filtered, scored and stored.
3. **Job list**: switch between *This search* and *All saved jobs*; sort by best match, newest, salary or
   company; filter by text, *New* (found since your last visit), *Has salary*, remote, visa and more.
   Each card shows the score with "Why this score", required and nice-to-have skills, experience range,
   salary, posting age, an AI verdict for the top matches, and a *limited info* tag when the posting said
   little. Card actions: **Save** (bookmark), **Resume check**, **Contacts**, **Apply manually**,
   **Auto-apply**, **Prepare**, and the eye/ban icons to hide a job or a whole company.
4. **Prepare application**: the agent writes a cover letter and fills the form in headless Chromium,
   attaching the resume version that fits the job best (or a tailored PDF). The application then appears
   in **Applications** as *Pending approval*, with screenshots, filled fields, open questions and an
   **Agent activity** timeline.
5. **Answer open questions**: for required questions the agent could not answer, it drafts an answer
   from your profile (marked as an AI draft). Correct it if needed, then **Save answers & re-fill**. Saved
   answers go to your **answer bank** and are reused on every later form that asks the same question.
6. **Approve & submit**: the agent re-opens the form, fills it with your (possibly edited) letter, and
   submits. It is marked *Applied* only after a confirmation message is detected.

**Auto-apply** does steps 4 and 6 without the review, but only when every required field is filled and
there is no visible CAPTCHA. Otherwise the application is handed back to you as *Needs manual*.

**Applications tab**: *Details* lists every application with its review tools; *Board* shows the pipeline
(Saved → To finish → Applied → Interviewing → Offer → Closed) with buttons to move cards along. *This week*
shows applications sent, interviews, offers and reply rates by kind of role, and can be emailed to you.
Applications with no news for `FOLLOW_UP_DAYS` (default 7) are flagged for a follow-up.

**Prepare tab**: interview insights for an application (skill gaps, topics to revise, likely questions)
and a **mock interview**: five questions, one at a time, with feedback on each answer and a summary.
Without an LLM, prepared questions from the posting are asked without feedback.

**Network tab**: import your LinkedIn connections (LinkedIn → Settings → Data privacy → Get a copy of your
data → Connections) to see who you already know at a company, plus recruiters and team members found
through web search (search results only; LinkedIn is never scraped). **Draft note** writes a short
connection note and message (AI-written, or a template).

**Resume versions** (Profile tab): keep versions for different kinds of roles. When applying, the version
covering most of the job's required skills is attached. **Resume check** (job card) compares a version
with the posting: keyword coverage, eight applicant-tracking readability checks, concrete suggestions,
and (with an LLM) three truthful tailoring tips.

**Tailored resume** ("Application Resume Mode: tailor"): the agent builds a PDF from your profile that
leads with the skills the posting asks for. Bullets are copied verbatim and only reordered.

Forms can be filled on Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, Teamtailor,
BambooHR and Personio. Other sites, including LinkedIn, Indeed, Naukri and Workday, are *Apply manually*:
JobPilot opens the site, drafts a letter to paste, and asks afterwards whether you applied.

### How search works

1. **Plan**: roles (typed, or your target roles) and locations become queries. JobPilot adds the other
   names the same job is posted under ("AI Engineer" → "Machine Learning Engineer", "LLM Engineer"…),
   skill-focused queries from your resume ("AI Engineer LLMs RAG Bengaluru"), a seniority variant
   ("Junior …" or "Senior …" from your years), and, with an LLM, titles and queries planned from your
   work history (cached for six hours per profile).
2. **Search** every source at once (next section). *Posted within* also limits web results by date.
3. **Verify** postings with the job board's API: real title, location and full description; closed
   postings are dropped.
4. **Filter**: the job must be the same *kind* of job as one of the searched titles (see below), fit your
   experience (no senior titles below 3.5 years, no internships once you have a year of experience,
   no "5+ years" when you have two), be in your locations (strict location), and pass the remote, visa,
   date and hidden-company filters. The search summary lists how many were removed and why.
5. **Rank**: score against your profile (next sections), then an AI review of the top 20.

**Role understanding.** Titles are read for their function (engineering, data science, sales, writing,
recruiting, data annotation, …), specialty (AI/ML, backend, frontend, DevOps, data engineering, mobile,
security…) and language. "Sales Engineer, AI", "AI Content Writer" and "AI Data Annotator" are not AI
engineering jobs; "Backend Engineer (Python)" is a Python developer job. A generic title such as
"Software Engineer II" counts as an AI role only when its description's skills are mostly AI skills.

### Where jobs come from

Everything uses only public, documented interfaces or your own email. LinkedIn, Indeed and Naukri are
never scraped or logged into. Feeds are cached (Remotive asks for at most a few requests a day), and every
job links back to its source page and shows the source's name.

| Source | How | Applying |
|---|---|---|
| **Company job boards** | Public job APIs of Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee and Personio: 80 built-in boards verified to list jobs in India or remote (cached 3 h), boards seen in search results, and your **watchlist** | Auto-fill (most) |
| **Web search** (SearXNG or Serper) | ATS-targeted queries, plus `site:` queries for LinkedIn, Naukri and Indeed job pages (`SEARCH_JOB_SITES`) | Auto-fill on ATS sites; manual on job sites |
| **Job feeds** | Remotive, Remote OK, Himalayas, Jobicy (remote jobs; skipped for on-site-only searches) and Arbeitnow | Manual |
| **Adzuna** (optional) | Job search API covering India and many countries, with salaries; free key at developer.adzuna.com | Manual |
| **Job-alert emails** | LinkedIn, Indeed and Naukri alerts read from your inbox (read-only IMAP) | Manual |

**Job-alert inbox**: put `IMAP_USER` and `IMAP_PASSWORD` in `.env` (for Gmail, an *app password*: turn on
2-step verification, then Google Account → Security → App passwords) and restart. The inbox is checked
every 30 minutes, or with **Check Inbox Now**. It is opened read-only. Only alert emails and emails naming
a company you applied to are downloaded; nothing about other emails is stored. The same check reads
replies from companies: "we received your application", interview invitations and rejections move the
application forward (never backwards) and are added to its timeline; for interview invitations an AI
reply draft is added for you to edit and send.

**Saved searches**: **Save search** stores the current search and runs it on a schedule (every 6/12/24
hours or weekly), adding new jobs and alerting you to strong new matches. **Scheduled discovery**
(`DISCOVERY_INTERVAL_HOURS`) runs your profile's search the same way.

**Alerts**: strong matches (`HIGH_MATCH_THRESHOLD`, default 85, passing all filters) are announced once
each to your Slack/Discord webhook and/or email. `ALERT_DIGEST_HOURS` sends a digest of new good matches;
`WEEKLY_REPORT_EMAIL=true` sends the weekly progress report.

**Full Auto-Pilot** (profile checkbox): after a scheduled search, applies on its own to at most
`AUTO_APPLY_DAILY_LIMIT` jobs per 24 hours (default 5), and only to jobs that score above the threshold,
match one of your target roles closely, are confirmed open on the company's board, and have a fillable
form. Each such application says "Started by Full Auto-Pilot" in its timeline.

### What the agent will not do

- **Invent data.** Unknown fields stay empty, and the letter, outreach and coaching prompts forbid
  made-up facts.
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
| Title | 25% | Role understanding (function, specialty, language) against your target roles or the searched roles |
| Skills | 35% | Required skills count fully, nice-to-have skills half; your own skills outside the catalogue (e.g. "MCP") count when the posting names them; short lists are shrunk toward "unknown" |
| Experience | 15% | The posting's range ("3-5 yrs", "0-2 years", "five years") against the range you chose or your years ±1 |
| Location | 15% | Remote and region restrictions, preferred locations, relocation |
| Sponsorship | 10% | Explicit evidence only. A posting that says "no sponsorship" fails the hard filter when you need it |

When the local model is ready, **resume similarity** (your resume vs. the full description) takes 14% of
the score, mostly from the skills share. Then:

- An unrelated title dampens the whole score; a job that fails a hard filter is capped at 35%.
- **Confidence**: a posting with almost no detail is marked *limited info* and capped at 80%, so it is never
  announced as a strong match on guesswork.
- **Learning from you**: jobs similar to ones you hid or dismissed lose up to 8 points; jobs similar to ones
  you applied to gain up to 8 (after at least two examples of each).
- **AI review** (with an LLM): the top 20 results get a verdict (*Strong / Possible / Weak / Not a fit*)
  with a one-line reason; strong adds 5 points, weak removes 12, "not a fit" caps the score at 40.
  Verdicts are cached per job and profile.

Expand "Why this score" on any job card to see every reason.

## API (prefix `/api/v1`)

Every endpoint except `/health` requires the API token when `API_TOKEN` is set
(`Authorization: Bearer <token>` or `X-API-Token: <token>`). Full schemas: http://localhost:8000/docs.

| Method & path | Purpose |
|---|---|
| `GET /health` | Component status (database, web search, LLM, Chromium, resume-similarity model) |
| `POST /search` · `POST /search/stream` | `{roles, locations, experience, posted_within, remote_only, sponsorship_required, strict_location, max_results}` → ranked jobs (persisted); the stream sends `stage` events, then `result` |
| `GET/POST /saved-searches` · `PATCH/DELETE /saved-searches/{id}` · `POST /saved-searches/{id}/run` | Saved searches and their schedule (`interval_hours`, `enabled`) |
| `GET /jobs?limit&include_closed&hidden` | Stored jobs, best match first (closed, hidden and blocked-company jobs left out) |
| `POST /jobs/{id}/hide` · `POST /jobs/{id}/unhide` | Not interested / undo |
| `POST /jobs/rescore` · `POST /jobs/recheck` · `DELETE /jobs` | Re-score every stored job (re-reading descriptions) · ask the boards which are still open · delete jobs without applications |
| `GET /jobs/{id}/resume-check?variant_id` | Resume vs. job: coverage, readability checks, suggestions, AI tips |
| `GET /jobs/company-contacts?company&job_title` · `GET /jobs/{id}/insiders` · `POST /jobs/outreach-message` | Network: connections, recruiters, team members; outreach drafts |
| `GET /boards` · `POST /boards` · `DELETE /boards/{ats}/{slug}` | Company boards searched directly; `POST {url}` watches a company |
| `GET /inbox` · `POST /inbox/check` | Job-alert inbox status · read new emails now |
| `GET/PUT /candidates/me` · `POST /candidates/me/resume` | Profile and main resume upload |
| `GET/POST /candidates/me/resumes` · `DELETE /candidates/me/resumes/{id}` | Resume versions (`file` + `label`) |
| `GET /candidates/me/connections` · `POST /candidates/me/connections/upload` | LinkedIn connections CSV |
| `GET /applications` · `POST /applications` | List; create `{job_id, mode: review\|auto\|manual\|save, tailor_resume?}` |
| `GET /applications/report?days` · `POST /applications/report/email` | Progress report · email it |
| `GET/PATCH /applications/{id}` | Read; edit `cover_letter` or set `APPLIED/INTERVIEW/OFFER/REJECTED/DISMISSED` |
| `POST /applications/{id}/approve` · `/refill` · `/follow-up` | Fill and submit · fill again · record a follow-up |
| `GET /applications/{id}/insights` · `POST /applications/{id}/mock-interview` | Interview prep · one mock-interview turn (`{messages}`) |
| `GET /applications/{id}/screenshot` · `/screenshots/{name}` · `/resume` | Screenshots and the tailored PDF |
| `GET/PUT /screening-answers` · `DELETE /screening-answers/{id}` | The answer bank |

Application statuses: `SAVED`, then `PROCESSING → PENDING_APPROVAL → SUBMITTING → APPLIED → INTERVIEW →
OFFER`, or `AWAITING_CONFIRMATION` (manual), `NEEDS_MANUAL`, `FAILED`, `REJECTED`, `DISMISSED`.

## Security

- **Bind to localhost.** The gateway listens on `127.0.0.1` by default (`BIND_ADDR`), and the compose
  file publishes ports on `127.0.0.1` only. The AI service is not published by compose at all.
- **API token.** Set `API_TOKEN` in `.env` whenever anyone but you can reach the service. Both the gateway
  and the AI service check it. The UI asks for it once and keeps it in the browser's local storage.
- **HTTPS certificates are verified** for every outgoing request, against both the operating system's
  certificate store and Mozilla's bundle, so company proxies with their own root certificate work.
  `CA_BUNDLE` adds a PEM file; `TLS_VERIFY=false` turns checking off (insecure, last resort).
- **CORS** allows only the local UI origins (`CORS_ORIGINS` to change).
- Resumes, tailored resumes, screenshots and the model cache live in `./data`, which git ignores. They
  contain personal data; delete the folder to remove everything.

## Project layout

```text
ai_service/app/
  main.py                    FastAPI app, error mapping, startup recovery, background runner, model warm-up
  core/                      settings (.env), logging, errors, API token, timeline entries, HTTPS, text/dates
  api/deps.py, api/routes/   dependency wiring; health, search, saved searches, jobs, candidates,
                             applications, screening answers, boards, inbox
  agents/search_agent/       LangGraph: plan queries → search → verify → filter → rank (streamable)
  agents/application_agent/  LangGraph: cover letter + resume → fill / submit form
  integrations/              Groq, SearXNG, Serper; browser/: Playwright runtime, form filler, PDF renderer;
                             mail/: read-only IMAP reader
  services/
    search/                  search service, company boards, job feeds, saved searches, discovery
    jobs/                    normalisation, requirements (skills, experience, salary), ATS detection,
                             de-duplication, enrichment, location, re-checks
    matching/                roles (title understanding), matching engine, resume similarity,
                             AI review, feedback learning
    skills/                  skill catalogue (~200 skills with domains)
    resume/                  parsing, versions, resume check, tailoring and layout
    applications/            application lifecycle, cover letters, insights, mock interview, report
    network/                 contacts and outreach
    notifications/           one-time alerts (webhook, email), digests
    inbox/, screening/, visa/, tasks/
  models/ schemas/ repositories/   SQLAlchemy models, Pydantic contracts, data access
ai_service/migrations/       Alembic migrations (run automatically on startup)
ai_service/tests/            pytest suite: unit, API, migrations, real-Chromium form filling and UI tests
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
while interrupted submits are handed back to you. The same loop re-checks stored jobs, reads the inbox,
runs due saved searches (checked every 15 minutes), scheduled discovery, and digest emails.

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

Periodic discovery from the command line, using your profile's preferred roles and locations:

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
`API_TOKEN` if the machine is shared. The AI service container runs as an unprivileged user; its data
volume also keeps the downloaded similarity model.

## Configuration

All settings are environment variables (see [.env.example](.env.example)). The most useful ones:

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | (none) | LLM for query planning, resume extraction and target roles, cover letters, answer drafts, AI review, interview coaching, outreach |
| `SEARXNG_URL` | `http://localhost:8080` | Web search |
| `WEB_SEARCH_PROVIDER`, `SERPER_API_KEY` | `searxng`, (empty) | `serper` uses Google results through Serper instead of SearXNG |
| `DATABASE_URL` | SQLite in `./data` | Any SQLAlchemy async URL (PostgreSQL in compose) |
| `API_TOKEN` | (empty: off) | Shared secret required on the API, checked by gateway and AI service |
| `TLS_VERIFY`, `CA_BUNDLE` | `true`, (empty) | HTTPS certificate checks; extra PEM file for company proxies |
| `SEMANTIC_MATCHING`, `SEMANTIC_MODEL` | `true`, `BAAI/bge-small-en-v1.5` | Local resume-to-description similarity |
| `LLM_REVIEW_TOP_N` | `20` | How many top results the AI reviews per search (`0` turns it off) |
| `SEARCH_JOB_SITES` | LinkedIn, Naukri, Indeed | Job sites added as `site:` web searches (`[]` disables) |
| `SEARCH_ENABLE_REMOTIVE` / `_ARBEITNOW` / `_REMOTEOK` / `_HIMALAYAS` / `_JOBICY` | `true` | Job feeds |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | (empty: off) | Adzuna job search API |
| `BROWSER_HEADLESS` | `true` | Set `false` to watch the agent fill forms |
| `BROWSER_MAX_CONCURRENCY` | `2` | Simultaneous Chromium instances |
| `TASK_MAX_ATTEMPTS` | `3` | Attempts per form fill (submits are never retried after the click) |
| `JOB_RECHECK_INTERVAL_HOURS` | `12` | How often stored jobs are re-verified (`0` disables) |
| `IMAP_USER`, `IMAP_PASSWORD` | (empty: off) | Job-alert inbox (Gmail: app password); also `IMAP_HOST`, `IMAP_FOLDER` |
| `INBOX_CHECK_INTERVAL_MINUTES` | `30` | How often the inbox is read (`0`: only with Check now) |
| `DISCOVERY_INTERVAL_HOURS` | `0` (off) | Run your profile's search automatically |
| `NOTIFICATION_WEBHOOK_URL`, `HIGH_MATCH_THRESHOLD` | (empty), `85` | Slack/Discord alerts for strong matches (each job once) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO` | (empty), `587` | Email alerts and reports (sent to `ALERT_EMAIL_TO`, else `SMTP_USER`) |
| `ALERT_DIGEST_HOURS`, `WEEKLY_REPORT_EMAIL` | `0`, `false` | Digest of new matches every N hours; weekly progress email |
| `AUTO_APPLY_DAILY_LIMIT` | `5` | Full Auto-Pilot: applications per 24 hours |
| `FOLLOW_UP_DAYS` | `7` | Flag applications with no news for this many days (`0` off) |

The gateway reads `BIND_ADDR` (default `127.0.0.1`), `PORT` (default 8090), `AI_SERVICE_URL`,
`CORS_ORIGINS` and `API_TOKEN`.
