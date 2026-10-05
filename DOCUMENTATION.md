# 🚀 JobPilot — Master Technical Documentation & Feature Specification

JobPilot is a state-of-the-art, modular autonomous job search engine and application agent. It decouples core business logic into a **Go Backend**, an **AI Agent Microservice in Python**, and a **Reactive Glassmorphic Frontend Dashboard**.

---

## 🏗️ 1. Directory Structure & Complete Code Inventory

```
jobpilot/
├── frontend/                   # High-Aesthetic Reactive Web UI
│   ├── index.html              # HTML5 dashboard structure
│   ├── styles.css              # Dark mode glassmorphic CSS design system
│   └── js/
│       ├── app.js              # Application entrypoint
│       ├── api.js              # Modular REST client to Go Backend
│       ├── state.js            # Global state manager (Pub/Sub pattern)
│       └── components/
│           ├── jobFeed.js      # Job card rendering, match gauges, visa pills
│           └── approvalQueue.js# Playwright Human-in-the-Loop review list
│
├── backend/                    # Go (Golang 1.22) Microservice (Port 8080)
│   ├── go.mod                  # Go module definition
│   ├── main.go                 # Compatibility root server entrypoint
│   ├── cmd/server/main.go      # Production Go server & HTTP multiplexer
│   ├── config/config.go        # Environment variable loader
│   └── internal/
│       ├── auth/
│       │   └── jwt.go          # JWT Token authentication & verification
│       ├── models/models.go    # Go domain structs (Job, Candidate, Application)
│       ├── clients/ai_client.go# HTTP client invoking Python AI Microservice
│       ├── repository/
│       │   └── application_repo.go # Thread-safe in-memory data access layer
│       └── handlers/
│           ├── handlers.go     # REST API route handlers
│           └── auth_handler.go # /api/v1/auth/register & /login handlers
│
├── ai_service/                 # Python FastAPI AI & Agentic Microservice (Port 8000)
│   ├── requirements.txt        # Python dependency manifest
│   ├── app/
│   │   ├── main.py             # FastAPI entrypoint & router mounting
│   │   ├── core/config.py      # Groq API & Pydantic settings
│   │   ├── agents/
│   │   │   ├── search_agent/   # LangGraph search agent & query re-creator
│   │   │   └── application_agent/ # LangGraph browser automation agent
│   │   ├── services/
│   │   │   ├── matching/matching_engine.py  # 3-stage candidate fit calculator
│   │   │   ├── visa/visa_service.py         # Natural language visa NLP parser
│   │   │   ├── applications/tailoring_service.py # LLM cover letter generator
│   │   │   ├── resume/resume_parser.py      # pdfplumber PDF resume extractor
│   │   │   ├── search/search_service.py     # Multi-source concurrent job search
│   │   │   └── notifications/webhook_service.py # Slack/Telegram webhook alerts
│   │   ├── schemas/            # Pydantic validation schemas
│   │   ├── models/             # SQLAlchemy ORM models
│   │   └── integrations/
│   │       ├── llm/llm_client.py           # Groq LLM API (openai/gpt-oss-120b)
│   │       ├── browser/playwright_client.py # Async Playwright Chromium agent
│   │       ├── captcha/captcha_solver.py    # 2Captcha reCAPTCHA solver
│   │       ├── search/searxng_client.py    # SearXNG metasearch HTTP client
│   │       └── vector/qdrant_client.py     # Qdrant 384-dim vector embeddings
│   └── workers/
│       ├── job_worker.py       # Background periodic discovery worker
│       └── email_tracker.py    # Employer email response status tracker
│
├── docker/
│   ├── Dockerfile.go           # Alpine multi-stage build for Go backend
│   └── Dockerfile.ai           # Python slim build with Playwright Chromium
├── docker-compose.yml          # Full-stack Docker orchestration
└── .gitignore                  # Production gitignore rules
```

---

## 🔬 2. Implemented Features & Architecture

### 2.1 🔑 JWT User Authentication & Multi-Tenancy
- **File**: `backend/internal/auth/jwt.go` & `backend/internal/handlers/auth_handler.go`
- **Endpoints**: `/api/v1/auth/register` & `/api/v1/auth/login`
- **Mechanism**: Generates HMAC SHA256-signed JWT tokens for authenticating candidates across sessions.

### 2.2 🧠 Groq LLM Query Re-creation & Cover Letter Tailoring
- **File**: `ai_service/app/integrations/llm/llm_client.py`
- **Model**: Groq `openai/gpt-oss-120b` (loaded via GROQ_API_KEY environment variable)
- **Mechanism**: Rewrites target roles into optimized search query matrices and generates 3-paragraph tailored cover letters.

### 2.3 🌐 Multi-Source Job Search Aggregator
- **File**: `ai_service/app/services/search/search_service.py`
- **Mechanism**: Concurrently queries **SearXNG Metasearch**, **Remotive Live Remote API**, and **Arbeitnow Job Board API** via `asyncio.gather`.

### 2.4 📄 PDF Resume Parser (`pdfplumber`)
- **File**: `ai_service/app/services/resume/resume_parser.py`
- **Mechanism**: Extracts text from PDF files, applying regex heuristics for candidate names, emails, phone numbers, experience years, and skill tags.

### 2.5 🤖 Auto-Apply & Human-in-the-Loop Browser Agent
- **File**: `ai_service/app/integrations/browser/playwright_client.py`
- **Modes**:
  - `auto_submit=False`: Human-in-the-Loop approval queue.
  - `auto_submit=True`: Automatically clicks form submit buttons and logs submission proof.

### 2.6 📧 Automated Email Status Tracker
- **File**: `ai_service/workers/email_tracker.py`
- **Mechanism**: Parses email responses from employers (`"Application Received"`, `"Interview Request"`, `"Regret to inform"`) and updates status to `INTERVIEW_SCHEDULED` or `REJECTED`.

### 2.7 🔔 Instant Notification Webhooks
- **File**: `ai_service/app/services/notifications/webhook_service.py`
- **Mechanism**: Delivers Slack, Telegram, or Discord JSON webhooks whenever high-fit jobs (**Match Score > 85%**) are discovered.

### 2.8 🧩 Anti-Captcha Solver Integration
- **File**: `ai_service/app/integrations/captcha/captcha_solver.py`
- **Mechanism**: Bypasses reCAPTCHA v2/v3 and Cloudflare challenges on complex ATS portals using 2Captcha API tokens.
