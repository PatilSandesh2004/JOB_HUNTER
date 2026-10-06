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
The first start upgrades your database automatically; your existing data is kept.

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

1. **Profile** tab: drop your resume (PDF/DOCX/TXT). Check the fields, set target roles and locations, then **Save profile**.
2. Optional, on the same tab: add saved answers ("How did you hear about us?" etc.) and tick **Attach a resume tailored to each job**.
3. **Discover** tab: type roles and locations, or click **From my resume**. Progress shows live.
4. On a job: **Prepare** (agent fills the form, you review), **Auto-apply**, or **Apply manually**.
5. **Applications** tab: answer any open questions, check the screenshot and letter, then **Approve & submit**.

If the page asks for an **access token**, enter the `API_TOKEN` from your `.env`.

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

More detail (features, API, configuration): see [DOCUMENTATION.md](DOCUMENTATION.md).
