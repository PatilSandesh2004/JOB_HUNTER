# Change report: search quality and workflow upgrade (October 2026)

This document records what changed in JobPilot after commit `81aeda6` ("updated hte features"), why, and
how each change was made. For how to use the features see [DOCUMENTATION.md](DOCUMENTATION.md); to run
the app see [HOW_TO_RUN.md](HOW_TO_RUN.md).

## Summary

The work had two goals: repair the regressions introduced by `81aeda6`, and fix the main complaint that
**search did not return jobs that actually match the candidate**. It then added the improvements and new
features agreed in the review.

| | Before | After |
|---|---|---|
| Python tests | 169, of which 23 failing | 258, all passing |
| CI (lint) | 92 ruff errors | clean (`ruff check`, `ruff format --check`) |
| "Sales Engineer, AI" for an AI Engineer | title score 93 (kept, ranked first) | 7 (dropped as a sales job) |
| "Machine Learning Engineer" for an AI Engineer | 77 | 89 |
| "Python Developer" for an AI Engineer | 0 (dropped even when the job is all LLM work) | 45, or 73 when the description is AI work |
| Skills recognised | ~70, tech only | ~200 in 15 domains, plus the candidate's own skills |
| "3-5 yrs", "0-2 years", "five years" | not understood | understood as ranges |
| Built-in company boards | 43 | 80, each verified against its live API |
| Job feeds | Remotive (called on every search), Arbeitnow | Remotive, Remote OK, Himalayas, Jobicy, Arbeitnow (cached), Adzuna (optional) |

**Live check** (an AI Engineer profile with 1.5 years in Bengaluru/Remote, real company boards and feeds,
without the LLM and without web search): 286 postings found, 34 kept, with 114 removed as unrelated roles,
56 as too senior, 18 as needing more experience and 29 as other locations. The top results were AI
engineering roles such as Composio "Applied AI Engineer" (Bangalore), Sarvam "Agent Engineer" (Bengaluru)
and ElevenLabs "Applied AI Engineer" (Remote).

## How the work was done

1. **Investigation.** Read the whole code base, ran the test suite (23 failures at `81aeda6`), and traced
   each failure to its cause. Ran the scoring functions directly against realistic job titles and posting
   text to measure why matches were poor (for example "Sales Engineer, AI" scoring 93 for an AI engineer).
2. **Repair first** (Phase 0), so later work started from a passing test suite.
3. **Check outside systems before relying on them.** Every job API used was called live to confirm its
   response fields (dates, salaries, descriptions) and its usage terms. Company boards were verified one by
   one. The embedding model was downloaded and calibrated on sample resumes and job descriptions.
4. **Measure, then fix.** Each rule (title understanding, skill extraction, experience and salary parsing)
   was developed against a set of real-world examples; every example became a pytest case.
5. **End-to-end check.** Ran a live search with real boards and feeds, inspected the ranked list, and tuned
   two rules that it exposed (see [Phase 1](#phase-1-accurate-matching), "Tuning from the live run").
6. **Verification.** Full test suite including real-browser UI tests, ruff lint and format checks, Go vet and
   tests, frontend syntax check, and `docker compose config`, matching what CI runs.

## Phase 0: repairs

| Problem | Effect | Cause | Fix |
|---|---|---|---|
| Search crash | Every search failed when the profile had no location (or no profile) | An `import LocationMatcher` inside `normalize_and_filter` made the name local to the whole function, so its later use raised `UnboundLocalError` | Removed the inline import; the foreign-country/no-sponsorship rule moved to a helper. The filter stage was later rewritten (`_Filters.drop_reason`) |
| UI actions broken | Hide job, hide company, Apply Manually, screenshots, tailored PDF, edit/delete saved answers, Save answers, remove watched company, Profile-tab sources/health all threw errors; Add answer, Watch company, Check inbox, Recheck and the modal ✕ did nothing | The `app.js` rewrite deleted 11 functions and several event listeners that the markup still used | Restored them in a reorganised `app.js`; the Network and Prepare tab rendering moved to `components/network.js` and `components/prepare.js` |
| Access token prompt missing | With `API_TOKEN` set, the UI could not log in | `auth.onUnauthorized` was no longer installed | Restored the token prompt |
| Profile save lost data | Saving the profile erased work experience, education and summary | `readProfileForm()` was called without the stored profile, so the missing fields were sent as empty | Pass `store.state.profile`; covered by a new browser test |
| Profile form would not submit | With years like 6.8 the browser silently refused to submit | The years field had `step="0.5"` | `step="any"` |
| Resume upload | The form went blank after an upload; drag-and-drop gone; jobs not re-scored | The UI read `res.candidate`, which the API never returns | Use the returned profile; restored drop zone and re-scoring after upload and save |
| Search box | A typed location was ignored when the role box was empty; boxes never pre-filled | Wrong condition; boot code read non-existent `profile.target_roles` | Locations always sent; pre-fill restored |
| Lost UI features | "Why this score", Auto-apply and Recheck buttons gone | Removed in the rewrite | Restored |
| HTTPS checks off | Certificate checks disabled in 6 places (`verify=False`) | Probably a workaround for a company proxy | New `core/http.py`: one SSL context trusting the OS certificate store (which includes company proxy roots on Windows) plus Mozilla's bundle; `CA_BUNDLE` adds a PEM file; `TLS_VERIFY=false` remains as a last resort |
| Job-site queries | 34 sites combined as `(site:a OR site:b …)`, which most engines ignore; most of those sites' links were not recognised as postings anyway | Over-broad change | One `site:` query per site again; default back to LinkedIn, Naukri and Indeed |
| `DELETE /jobs` removed | Documented endpoint returned 405 | Dropped in the rewrite of `jobs.py` | Restored |
| Interview prep | The UI crashed when the LLM omitted a field; without an LLM the endpoint failed | Service built with a session factory instead of a session (it worked only because the route passed its own); no output validation | Rewritten `insights_service.py`: validated lists, 404 for unknown applications, a template fallback without an LLM |
| Outreach messages | Crashed without a profile; ignored the job title | `candidate.current_role` on `None`; untyped `dict` body | Typed `OutreachRequest`; `services/network/outreach.py` with a template fallback and LinkedIn's 300-character limit |
| LinkedIn connections import | Imported zero rows; no button in the UI | LinkedIn's CSV starts with "Notes:" lines before the header | `parse_connections_csv` starts at the real header; import button and count added to the Network tab |
| Alerts | The same jobs were re-announced on every search; email blocked the server for up to 15 s; job titles inserted unescaped into email HTML; fallback recipient `user@example.com` | No memory of what was sent; synchronous SMTP | `MatchAlertService` announces each job once (`jobs.notified_at`), email runs in a worker thread, HTML is escaped, `ALERT_EMAIL_TO` added |
| Full Auto-Pilot | Could auto-apply to any job scoring ≥ 85, e.g. a mis-scored sales role | No safety rules | Only verified, fillable jobs with a close title match, at most `AUTO_APPLY_DAILY_LIMIT` per 24 hours, never a job you already have an application for; each one says "Started by Full Auto-Pilot" |
| Remotive usage | Called on every search, against Remotive's terms (at most ~4 requests a day) | No caching | All feeds cached (see Phase 3) |
| Lint | 92 ruff errors, CI red | Formatting and unused imports in `81aeda6` | Fixed and formatted |

The UI tests were updated for the new tab layout (`discover-tab` → `jobs-tab`, the System section now lives
in `profile-tab`).

## Phase 1: accurate matching

### Role understanding (`services/matching/roles.py`, new)

Old behaviour: a job matched when the target's words appeared in its title, so any title containing "AI"
matched "AI Engineer", and titles without the word ("Python Developer") were dropped.

New behaviour: every title is parsed into a `TitleProfile`:

- **Function**: the first matching rule of 21, specific before general (annotation, recruiting, sales,
  marketing, content, design, product, support, QA, developer relations, data science, research, business
  analysis, analytics, IT operations, finance, legal, education, operations, management, engineering).
  "Sales Engineer", "Solutions Architect" and "Customer Engineer" are sales; "AI Code Trainer" and "Data
  Annotator" are annotation; "Business Systems Engineer" is business analysis.
- **Specialties**: AI/ML, backend, frontend, mobile, DevOps/cloud, data engineering, security, embedded,
  blockchain, game, enterprise apps (full stack = frontend + backend).
- **Languages**: Python, Java, JavaScript/TypeScript, Go, Rust, C++, C#, Ruby, PHP, Scala, Kotlin, Swift,
  with families (Java/Kotlin/Scala).
- **Keywords**: remaining meaningful words, e.g. "payments".

`role_similarity(target, title, job_skills)` combines them:

```text
score = 100 × function_fit × (w1·specialty_fit + w2·language_fit + w3·keyword_fit) × 0.88 + 12 × fuzzy
weights: (0.7, 0.2, 0.1) normally; (0.3, 0.6, 0.1) for language-led targets ("Python Developer");
         (0.55, 0.35, 0.1) when the target has both
```

- `function_fit` is 1 for the same function, a small table value for related ones (engineering ↔ QA 0.35,
  data science ↔ research 0.7…), 0.65 for engineering ↔ data science when both are AI, and 0 for
  unrelated ones (engineering ↔ sales).
- `specialty_fit`: same specialty 1.0; adjacent specialties partial credit (backend ↔ data engineering
  0.4…); a generic title ("Software Engineer II") 0.3 unless its **description's skills** show the work
  (0.75), which uses `specialties_from_skills` (at least 2 skills and at least 25% of the posting's skills
  in that domain).
- A job is relevant at **55 or more**. Calibrated on 49 title pairs; 26 of them are regression tests.

`related_titles()` lists the other names a job is posted under (AI Engineer → Machine Learning Engineer,
LLM Engineer, Generative AI Engineer…); they are used for queries and for the relevance check.

### Skill catalogue (`services/skills/catalog.py`, rewritten)

- About 200 canonical skills in 15 domains (languages, backend, databases, frontend, mobile, AI, data
  engineering, analytics, cloud/DevOps, security, QA, design, product, business, general), including the
  GenAI stack (RAG, agents, MCP, function calling, LLM evaluation, vector databases, LangGraph…).
- Words that are also ordinary English only count in their technical spelling and context, through
  case-sensitive aliases (`cs(...)`) and look-arounds: "React quickly" and "react to" are not React, "excel
  at" is not Excel, "Go to market" is not Go, "RAG status" is not RAG, "Spring 2026" is not Spring.
- Speed: each skill has trigger words checked with a plain substring test before its regex runs. Extraction
  went from about 86 ms to 7 ms per 8 KB description.
- `candidate_skill_profile()` maps the candidate's free-text skills to catalogue skills ("SQL (PostgreSQL)"
  → SQL and PostgreSQL); skills outside the catalogue (e.g. "Groq") are matched literally in the job
  description; soft skills are ignored.

### Reading postings (`services/jobs/requirements.py`, new)

- **Sections**: headings in the flattened text label each part as required ("Requirements", "Must have"),
  nice-to-have ("Nice to have", "Bonus"), job content ("Responsibilities", "About this role") or ignored
  ("About us", "About <Company>", "Benefits", equal-opportunity text). `split_skills()` returns required and
  nice-to-have skills; an inline "(preferred)" or "is a plus" also marks a skill as nice-to-have.
- **Experience**: finds ranges and minimums ("3-5 yrs", "0-2 years", "minimum five years", "4 to 6 years");
  only within the same sentence as "experience"; ignores company-age phrases ("founded 15 years ago", "we
  have grown for 12 years"); ignores nice-to-have statements; takes the largest required minimum as the
  bar; "freshers", "entry level" and "new graduates" mean 0–1 years.
- **Salary**: ₹ LPA ranges and single values, "₹12L–₹18L", "INR 8,00,000 – 12,00,000", "$120k–$150k",
  "USD 90,000–110,000", €/£, per hour/month; plausibility checks; funding amounts ("$50M–$100M raised") are
  rejected. Structured salaries from APIs take precedence.

`refresh_requirements()` re-reads stored descriptions, so `POST /jobs/rescore` upgrades jobs saved by older
versions.

### Matching engine (`services/matching/matching_engine.py`, rewritten)

| Part | Change |
|---|---|
| Title (25%) | `role_similarity` against the searched roles, or the profile's target roles and current role; the reason names the kind of job ("Different kind of job: sales") |
| Skills (35%) | Required skills count fully, nice-to-have half; your own skills found in the description count; no recognisable skills scores 45 (was 60), so unknown postings no longer outrank real partial matches |
| Experience (15%) | Uses the posting's range; without a chosen range, the candidate's years −1 to +1.5, the same band the search uses, so search and re-score give identical scores; internships are flagged once you have a year of experience |
| Confidence | HIGH / MEDIUM / LOW from description length, skills, experience and location; LOW is shown as "limited info" and capped at 80 so it never triggers a strong-match alert |

### Search agent (`agents/search_agent/graph.py`, rewritten)

- **Query plan**: four sources interleaved so each survives the cap of 10 queries: role × location (with
  both city spellings), resume queries (the role plus the candidate's skills that belong to that kind of
  work, e.g. "AI Engineer LLMs RAG Bengaluru", plus "Junior …" or "Senior …" by years), related titles, and
  the LLM plan. The LLM prompt now includes recent work history and returns titles, queries and key skills;
  the plan is cached for six hours per profile and search.
- **Filters**: one `_Filters.drop_reason()` per job, in order: unrelated role, seniority mismatch, needs more
  experience, too junior, company you hid, not remote, no sponsorship, abroad without sponsorship, no
  posting date / posted too long ago (when a date filter is set), other location. The counts are shown
  under the search box.
- **Dates**: "Posted within" is passed to web search (`time_range` for SearXNG, `tbs` for Serper) and to
  Adzuna; undated jobs are left out when a date filter is set.
- **De-duplication** (`deduplication_service.py`): the place is part of the comparison, so the same title in
  Bengaluru and Toronto stays as two jobs; a copy without a place merges with the one that states it; the
  most informative copy is kept (verified, dated, longer description).

### Target roles from the resume

The resume-extraction prompt also asks for up to four target roles. They fill the profile's Target Roles
only when the user has not set any (`candidates.py` `_merge_into`).

### Tuning from the live run

- Greenhouse boards of Coinbase, Elastic, Stripe and others link to the company's careers site, so the
  description was never fetched ("limited info"). Board postings now carry `board` and `board_job_id`, and
  enrichment asks Greenhouse's API with them.
- "Business System Engineer" scored 77 because two of its eight skills were AI skills; business-systems
  titles are now business analysis, and the 25% share rule was added for description evidence.

## Phase 2: AI matching

| Part | How it works |
|---|---|
| Resume similarity (`matching/semantic.py`) | `fastembed` with `BAAI/bge-small-en-v1.5` (about 65 MB, CPU). Loaded in the background at startup into `data/models`. Compares a resume text (role, summary, skills, last four jobs) with each description of 200+ characters (first 2,000 characters). Calibrated on samples: same work 0.889, classic ML 0.734, AI content writer 0.698, Java backend 0.673, frontend 0.588, sales 0.585; mapped 0.60 → 0 and 0.88 → 100. Vectors are cached. When ready it takes 14% of the score (title 24, skills 25, experience 14, location 14, sponsorship 9). Without the model, scoring works as before. |
| AI review (`matching/reviewer.py`) | The top 20 results that pass the filters are sent to the LLM in batches of 8 with the candidate's facts; each gets `strong / possible / weak / no` and a reason of up to 20 words. Strong +5, weak −12, "no" caps the score at 40. Cached per job and profile fingerprint; re-scoring re-applies a verdict while the profile is unchanged (`ai_profile`). `LLM_REVIEW_TOP_N=0` turns it off. |
| Learning from you (`matching/feedback.py`) | Liked: jobs with an application you engaged in (applied, interview, offer, pending approval…). Disliked: hidden jobs and dismissed applications. Similarity = 0.75 × title similarity + 0.25 × shared skills; above 0.65 it moves a score by up to ±8 points, with a reason. Needs at least two examples of a kind. |

## Phase 3: more and better jobs

- **Company boards** (`search/board_source.py`): 228 candidate companies were checked against the
  Greenhouse, Lever and Ashby APIs; 80 boards that list jobs in India or remote (at least five, or a
  meaningful share) became the built-in list (42 Greenhouse, 11 Lever, 27 Ashby). Large boards with almost
  no local jobs were left out (e.g. Cloudflare 3 of 424). A full refresh is about 58 MB in 17 s, so boards
  are cached for 3 hours. Borderline titles with a description are re-judged with their skills; borderline
  titles without one (Greenhouse lists) are kept for the agent to judge after fetching the description.
- **Posting dates** from every board API (`first_published`, `createdAt`, `publishedAt`, `published_on`,
  `releasedDate`, `published_at`, Personio `createdAt`); salaries from Lever `salaryRange` and Ashby
  compensation.
- **Descriptions**: SmartRecruiters listings now fetch their job details; custom-domain Greenhouse jobs use
  the board id (see above).
- **Feeds** (`search/feeds.py`, new): Remotive (cached 6 h, per its terms), Remote OK (6 h), Himalayas and
  Jobicy (3 h per query), Arbeitnow (1 h), Adzuna (optional key, 3 h, country from your locations). Each
  is filtered locally by title, links back to its own page and shows its name, as their terms require.
  Remote-only feeds are skipped for on-site-only searches.
- **Text and dates** (`core/text.py`, new): HTML to text, repair of mis-encoded text ("weâ€™re" → "we're"),
  and dates in ISO, Unix seconds/milliseconds and relative form ("3 days ago").

## Section 3 improvements and section 4 features

| Feature | Backend | UI |
|---|---|---|
| Job list | `first_seen_at` on jobs | *This search* / *All saved jobs*, sort (match, newest, salary, company), text filter, quick filters *New* and *Has salary*, "New" badge since your last visit, 30 per page; cards show AI verdict and reason, salary, posting age, experience range, *limited info*, nice-to-have chips, Save and Resume check |
| Saved searches | `saved_searches` table, `SavedSearchService`, `/saved-searches` API, checked every 15 minutes | **Save search** dialog with a schedule; list with Run, Pause, Delete and interval |
| Alerts | `jobs.notified_at`; `DigestService` (`ALERT_DIGEST_HOURS`, `WEEKLY_REPORT_EMAIL`; state in `data/digests.json`) | — |
| Application board | Statuses `SAVED` and `OFFER`, mode `save`, starting an application from a saved job | *Board* view: Saved → To finish → Applied → Interviewing → Offer → Closed, with move buttons |
| Follow-ups | `follow_up_due` after `FOLLOW_UP_DAYS`; `POST /applications/{id}/follow-up` | Banner, badges, "Followed up" button |
| Weekly report | `report_service.py`; `GET /applications/report`, `POST /applications/report/email` | *This week* card with reply and interview rates by kind of role |
| Resume versions | `resume_variants` table, `ResumeLibrary`; the best-covering version is attached when applying | Profile tab list, upload with a label, delete |
| Resume check | `resume_check.py`: keyword coverage, 8 applicant-tracking checks, suggestions, LLM tips | Modal from the job card |
| Mock interview | `interview_coach.py`: five questions with feedback and a summary (LLM), prepared questions otherwise | Chat in the Prepare tab |
| Health | Resume-similarity model status; web-search provider | Two health cards |

## Data model and migrations

| Migration | Change |
|---|---|
| `0005` | Reformatted only (same schema) |
| `0006_job_alert_tracking` | `jobs.notified_at` |
| `0007_job_requirements` | `jobs.experience_max`, `jobs.preferred_skills` (JSON, default `[]`), `jobs.salary_period` |
| `0008_saved_searches_and_resume_versions` | Tables `saved_searches` and `resume_variants` (FK to `candidates`, cascade on delete) |

Migrations run automatically on startup; `test_migrations.py` checks upgrade, downgrade and adoption of
pre-Alembic databases.

## API changes

New: `GET/POST /saved-searches`, `PATCH/DELETE /saved-searches/{id}`, `POST /saved-searches/{id}/run`,
`GET /jobs/{id}/resume-check`, `GET/POST /candidates/me/resumes`, `DELETE /candidates/me/resumes/{id}`,
`GET /candidates/me/connections`, `GET /applications/report`, `POST /applications/report/email`,
`POST /applications/{id}/follow-up`, `POST /applications/{id}/mock-interview`.

Changed: `POST /applications` accepts `mode: "save"`; statuses `SAVED` and `OFFER`; `PATCH /applications/{id}`
accepts `OFFER`; `GET /jobs/company-contacts` accepts `job_title`; `POST /jobs/outreach-message` has a typed
body; `GET /health` reports the similarity model; job objects include `experience_max`, `preferred_skills`,
`salary_period`, `first_seen_at`; match objects include `missing_preferred`, `confidence`,
`semantic_match`, `ai_verdict`, `ai_reason`. Restored: `DELETE /jobs`.

## Configuration

New settings (all optional): `TLS_VERIFY`, `CA_BUNDLE`, `SEMANTIC_MATCHING`, `SEMANTIC_MODEL`,
`LLM_REVIEW_TOP_N`, `SEARCH_ENABLE_REMOTEOK`, `SEARCH_ENABLE_HIMALAYAS`, `SEARCH_ENABLE_JOBICY`,
`ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `ALERT_EMAIL_TO`, `ALERT_DIGEST_HOURS`, `WEEKLY_REPORT_EMAIL`,
`AUTO_APPLY_DAILY_LIMIT`, `FOLLOW_UP_DAYS`. `SEARCH_JOB_SITES` defaults back to LinkedIn, Naukri and
Indeed. See [.env.example](.env.example) and the table in [DOCUMENTATION.md](DOCUMENTATION.md#configuration).

## Dependencies

`fastembed>=0.4` was added to `ai_service/requirements.txt`; `scripts/lock_deps.py` added its pins
(fastembed 0.9.0, onnxruntime 1.30.0, numpy 2.4.6, tokenizers 0.23.2, huggingface-hub 1.33.0 and their
dependencies) without changing existing pins.

## Tests

| File | Tests | Covers |
|---|---|---|
| `test_search_quality.py` (new) | 67 | Role understanding, skill extraction in context, experience and salary parsing, sections, de-duplication, scoring rules and confidence, resume-based query planning and its cache, date filters, feeds (filtering, caching, salaries, dates), board dates, SmartRecruiters and custom-domain Greenhouse descriptions |
| `test_network_and_alerts.py` (new) | 7 | LinkedIn CSV, contacts, outreach fallback, insights fallback, one-time alerts, Auto-Pilot rules and daily limit |
| `test_ai_matching.py` (new) | 4 | Resume similarity (with a stand-in model) and caching, AI review and carry-over, feedback learning |
| `test_workflow_features.py` (new) | 6 | Saved jobs to offer, follow-ups and report, saved searches and schedule, resume versions and check, mock interview, digests |
| `test_ui.py` | 6 (3 new) | Real-browser tests: profile save keeps work history; job list tools, saving and resume check; saved searches, resume versions and mock interview |
| `test_resume_parser.py` | 8 (2 new) | Target-role suggestions and keeping roles you set |

Test setup changes: `SEMANTIC_MATCHING=false` in tests (no model download), the fake search service accepts
the new search options, and the application service fixture includes the resume library.

## Upgrading an existing install

1. `.venv\Scripts\python -m pip install -r requirements.txt` (adds `fastembed`). With Docker:
   `docker compose up --build -d`.
2. Start the app. The database is upgraded automatically (keep a copy of `data\jobpilot.db` if you want a
   fallback), and the similarity model downloads in the background on the first start.
3. Open **Profile Settings** and click **Save Profile Settings** once, so stored jobs are re-read and
   re-scored with the new rules. Check the suggested Target Roles after uploading a resume.

## Known limitations

- The Adzuna integration follows Adzuna's documented API and is tested against a mocked response; it has
  not been run with a real key.
- LLM features (query planning, AI review, resume tips, adaptive mock interviews, target roles) use the
  Groq quota. Results are cached; `LLM_REVIEW_TOP_N=0` turns the review off.
- Title understanding is rule-based. Unusual titles fall back to "other" and are judged by their details.
- The first search after a start downloads the company boards (~60 MB); the similarity model needs internet
  for its first download (matching works without it).
- Remote feeds carry few India-specific roles; the built-in boards lean towards technology companies. Add
  any company with the watchlist.

## Files

New backend modules: `core/http.py`, `core/text.py`, `services/matching/{roles,semantic,reviewer,feedback}.py`,
`services/jobs/requirements.py`, `services/search/{feeds,saved_search_service}.py`,
`services/network/{contacts,outreach}.py`, `services/notifications/{alerts,digest}.py`,
`services/resume/{library,resume_check}.py`, `services/applications/{interview_coach,report_service}.py`,
`api/routes/saved_searches.py`, `models/{saved_search,resume_variant}.py`, migrations `0006`–`0008`.

New frontend components: `components/{board,interview,network,prepare,resumes}.js`.

Rewritten: `agents/search_agent/graph.py`, `services/matching/matching_engine.py`,
`services/skills/catalog.py`, `services/search/search_service.py`, `services/jobs/deduplication_service.py`,
`services/applications/insights_service.py`, `services/notifications/{email,webhook}_service.py`,
`api/routes/jobs.py`, `frontend/js/app.js`, `frontend/js/components/jobFeed.js`.
