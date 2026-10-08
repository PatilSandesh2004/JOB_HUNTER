# How to run JobPilot

Two ways to run it. Pick one:

- **A. Locally on Windows** (recommended while developing): Python + Go on your machine.
- **B. With Docker**: everything in containers, nothing else to install.

Either way, you end up opening **http://localhost:8090** in your browser.

---

## A. Run locally (Windows)

### 1. Install once

You need **Python 3.11+**, **Go 1.22+** and **Docker Desktop** (Docker is only for SearXNG, the search engine).

Open PowerShell in the project folder (`JOB_HUNTER`) and run:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium
```

### 2. Create your settings file

```powershell
copy .env.example .env
notepad .env
```

In `.env`, set at least:

| Setting | What to put |
|---|---|
| `GROQ_API_KEY` | Your key from https://console.groq.com (optional: without it you get template cover letters and no AI answer drafts) |
| `SEARXNG_URL` | `http://localhost:8080` (the default, matches step 3) |
| `API_TOKEN` | Optional on your own PC. Set one if anyone else can reach your machine: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |

### 3. Start SearXNG (job search engine)

Run once; it keeps running in the background and restarts with Docker:

```powershell
docker run -d --name searxng --restart unless-stopped -p 127.0.0.1:8080:8080 `
  -v "${PWD}\searxng\settings.yml:/etc/searxng/settings.yml:ro" `
  -e SEARXNG_SECRET=change-me-to-a-random-string searxng/searxng
```

Check it: http://localhost:8080 should show a search page.

### 4. Start JobPilot

```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
```

This opens two windows: the AI service (port 8000) and the web gateway (port 8090).
The first start upgrades your database automatically; your existing data is kept. It also downloads the
resume-similarity model (about 65 MB) into `data\models` in the background; searches work meanwhile.

> **Updating an existing install?** Install the new dependencies first, then start as usual:
> ```powershell
> .venv\Scripts\python -m pip install -r requirements.txt
> ```
> After the first start, open **Profile Settings** and click **Save Profile Settings** once: your stored
> jobs are re-scored with the new matching.

Open **http://localhost:8090**.

To stop: press **Ctrl+C** in both windows (or close them).

> **No Go installed?** Run only the AI service; it serves the same UI at http://localhost:8000:
> ```powershell
> .venv\Scripts\python -m uvicorn ai_service.app.main:app --host 127.0.0.1 --port 8000
> ```

---

## B. Run with Docker

```powershell
copy .env.example .env
notepad .env
```

In `.env`, set `GROQ_API_KEY`, and **these two are required** (any random strings):

```text
POSTGRES_PASSWORD=pick-a-password
SEARXNG_SECRET=pick-a-long-random-string
```

Then:

```powershell
docker compose up --build -d
```

Open **http://localhost:8090**. (SearXNG is at http://localhost:8081.)

| Task | Command |
|---|---|
| See logs | `docker compose logs -f ai_service` |
| Stop | `docker compose down` |
| Stop and delete all data | `docker compose down -v` |

Docker uses its own PostgreSQL database, separate from the local SQLite one in `data/`.

---

## First use

1. **Profile Settings** tab: drop your resume (PDF/DOCX/TXT). With a Groq key, target roles are suggested
   from it. Check the fields, set target roles and locations, then **Save Profile Settings**.
2. Optional, on the same tab: add **resume versions** (e.g. "AI" and "Backend"; the best one is attached
   to each application), saved form answers ("How did you hear about us?" etc.), and your company watchlist.
3. **Jobs** tab: type roles and locations, or leave the role empty to search from your resume. Progress
   shows live. Use the sort and filter bar above the results; **Save search** runs it on a schedule.
4. On a job: **Save** (bookmark icon), **Resume check**, **Contacts**, **Prepare** (agent fills the
   form, you review), **Auto-apply**, or **Apply manually**.
5. **Applications** tab: answer any open questions, check the screenshot and letter, then **Approve &
   submit**. Switch to **Board** to move applications from Saved to Offer; follow-ups are flagged.
6. **Prepare** tab: interview insights and a five-question **mock interview** for any application.

If the page asks for an **access token**, enter the `API_TOKEN` from your `.env`.

On any job card: the **eye icon** hides a job you're not interested in (similar jobs then rank lower), and
the **ban icon** hides every job from that company (undo from the toast, or in Profile → Hidden companies).

---

## Optional: more job sources

**Watch companies** (System tab → Company watchlist): paste any job or careers link from Greenhouse,
Lever, Ashby, Workable, SmartRecruiters, Recruitee or Personio, e.g. `https://jobs.lever.co/cred`.
That company's whole job board is searched from then on.

**Jobs from LinkedIn / Indeed / Naukri alerts** (read from your own email, read-only):

1. On LinkedIn, Indeed and/or Naukri, create job alerts sent to your email.
2. Gmail: turn on **2-step verification**, then create an **app password**
   (Google Account → Security → App passwords). Copy the 16-character password.
3. In `.env`:
   ```text
   IMAP_USER=you@gmail.com
   IMAP_PASSWORD=your-16-char-app-password
   ```
4. Restart JobPilot. The System tab → **Job-alert inbox** shows the status; click **Check now** or wait
   (it checks every 30 minutes). Replies from companies you applied to also update those applications.

**Automatic searches**: press **Save search** on the Jobs tab (choose how often it runs), or set
`DISCOVERY_INTERVAL_HOURS=6` in `.env` to run your profile's search every 6 hours.

**More jobs from Adzuna** (covers India, includes salaries): get a free key at developer.adzuna.com and set
`ADZUNA_APP_ID` and `ADZUNA_APP_KEY` in `.env`.

**Email alerts and reports**: set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` (Gmail: an app
password) and optionally `ALERT_EMAIL_TO`. Strong new matches are emailed once each;
`ALERT_DIGEST_HOURS=24` adds a daily digest and `WEEKLY_REPORT_EMAIL=true` a weekly progress report.

---

## Run the tests

```powershell
.venv\Scripts\python -m pytest                     # Python + browser tests (~1 min)
cd backend; go test ./...; cd ..                   # Go gateway tests
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Search shows SearXNG errors / HTTP 403 | SearXNG must use `searxng\settings.yml` (JSON output on). Recreate the container from step 3. |
| "too many requests" / CAPTCHA in search errors | Search engines rate-limit; wait a few minutes and search again. |
| System tab: Browser agent DOWN | `.venv\Scripts\python -m playwright install chromium` |
| Port 8000 or 8090 already in use | Close the old JobPilot windows, or find it: `Get-NetTCPConnection -LocalPort 8090` |
| UI keeps asking for the token | The token must match `API_TOKEN` in `.env`; restart after changing `.env`. |
| `docker compose` says "Set POSTGRES_PASSWORD" | Add `POSTGRES_PASSWORD` and `SEARXNG_SECRET` to `.env`. |
| LLM shows DOWN on the System tab | Set a valid `GROQ_API_KEY` in `.env` and restart. The app still works without it. |
| Inbox: "Login failed … app password" | Use a Gmail **app password**, not your normal password (needs 2-step verification). |
| Inbox finds alerts but 0 jobs | Alert layouts change; check the alerts are from LinkedIn/Indeed/Naukri and contain job links. Open an issue with the email's layout. |
| "Watch company" says the link isn't supported | Only Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee and Personio boards can be watched. |
| Searches fail with certificate (SSL) errors at work | Your company proxy uses its own certificate. Install it in Windows, or set `CA_BUNDLE=C:\path\to\proxy-ca.pem`. `TLS_VERIFY=false` works but is insecure. |
| System tab: Resume similarity DOWN / unavailable | The model could not be downloaded (no internet or blocked). Matching still works without it; restart once you are online. |
| First search after starting is slow | The company boards (~60 MB) are downloaded once and cached for 3 hours. |

More detail (features, API, configuration): see [DOCUMENTATION.md](DOCUMENTATION.md).
