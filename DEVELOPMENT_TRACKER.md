# JobPilot — Development Tracker

- **Last updated**: October 8, 2026
- **Stack**: Go 1.22 gateway (`backend/`), Python 3.11+ FastAPI + LangGraph AI service (`ai_service/`),
  vanilla JS UI (`frontend/`), SQLite or PostgreSQL, SearXNG or Serper, Groq (optional), fastembed (local model)
- **Tests**: 258 Python tests (unit, API, migrations, real-browser form filling and UI) + Go tests, all passing

See [DOCUMENTATION.md](DOCUMENTATION.md) for how each feature works, [HOW_TO_RUN.md](HOW_TO_RUN.md) to run it,
and [CHANGES_2026-10.md](CHANGES_2026-10.md) for what changed in October 2026 and how.

## Done

### Search quality (October 2026)
- [x] Role understanding: job function, specialty and language (no more "Sales Engineer, AI" for AI engineers)
- [x] Queries built from the resume: target roles, related titles, relevant skills, seniority, LLM plan (cached)
- [x] Target roles suggested from the resume on upload
- [x] Skill catalogue of ~200 skills with domains and context rules ("React quickly" is not React)
- [x] Required vs nice-to-have skills; company blurbs and benefits ignored
- [x] Experience ranges ("3-5 yrs", "0-2 years", "five years"), company-age phrases ignored
- [x] Posting dates from every board and feed; "posted within" filters web search too
- [x] Location-aware de-duplication keeping the richest copy
- [x] Confidence: "limited info" postings capped below the alert threshold
- [x] Resume similarity with a local embedding model
- [x] AI review of the top 20 results (verdict + reason, cached)
- [x] Learning from hidden, dismissed and applied jobs
- [x] Same scoring rules for search and re-score; stored jobs re-read with the current parsers

### Sources
- [x] 80 verified company boards (Greenhouse, Lever, Ashby) with India/remote jobs, cached 3 hours
- [x] Feeds: Remotive, Remote OK, Himalayas, Jobicy, Arbeitnow (cached per their terms); Adzuna (optional key)
- [x] Salaries from APIs and text (LPA, ₹, $, €, £; per year/month/hour)
- [x] SmartRecruiters and custom-domain Greenhouse jobs get their full descriptions

### Workflow
- [x] Job list: this search / all saved jobs, sort, text filter, "New" since last visit, paging
- [x] Saved searches on a schedule; one-time alerts per job; daily digest and weekly report emails
- [x] Applications board (Saved → To finish → Applied → Interviewing → Offer → Closed), follow-up reminders
- [x] Weekly progress report by kind of role
- [x] Resume versions with automatic best-fit choice; resume-vs-job check with ATS readability
- [x] Mock interview (adaptive with an LLM, prepared questions without)
- [x] Network: LinkedIn connections CSV, recruiters and team members, outreach drafts
- [x] Full Auto-Pilot with a daily cap, verified jobs and close title matches only

### Reliability and security
- [x] HTTPS certificate checks on every outgoing request (OS store + Mozilla; CA_BUNDLE for proxies)
- [x] Repaired regressions from commit 81aeda6: search crash, lost UI actions, token prompt, profile-save data loss

## Ideas for later
- [ ] Voice mode for the mock interview
- [ ] Company insights on job cards (size, funding, ratings)
- [ ] Browser extension to save jobs from any site
