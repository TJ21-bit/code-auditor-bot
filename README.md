# Code Auditor Bot — 88gravity

AI-powered code auditor. Pulls code from GitHub → audits with Claude → raises issues → parks to Jira + Google Sheets → assigns owners → follows up after 48 hours.

---

## Quick Start

```bash
# 1. Clone / create the project
cd code-auditor-bot

# 2. Set up environment
cp .env.example .env
# Edit .env and fill in all keys (see below)

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
uvicorn app.main:app --reload
# → http://localhost:8000
```

## Docker

```bash
docker-compose up --build
```

---

## Environment Variables

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Your Claude API key |
| `GITHUB_TOKEN` | GitHub PAT with `repo` read scope |
| `GITHUB_WEBHOOK_SECRET` | Secret for verifying push webhooks |
| `JIRA_BASE_URL` | e.g. `https://yourteam.atlassian.net` |
| `JIRA_EMAIL` | Your Jira account email |
| `JIRA_API_TOKEN` | Jira API token |
| `JIRA_PROJECT_KEY` | e.g. `DEV` |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Path to service account JSON file |
| `GOOGLE_SHEET_ID` | ID from the Google Sheets URL |
| `GOOGLE_SHEET_TAB` | Tab name, default `Code Issues` |
| `SMTP_HOST` / `SMTP_PORT` | Email server for follow-up notifications |
| `SMTP_USER` / `SMTP_PASS` | Email credentials |
| `SLACK_WEBHOOK_URL` | Incoming webhook for Slack alerts |
| `FOLLOWUP_INTERVAL_HOURS` | Hours before first follow-up, default `48` |

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/audit/` | Trigger audit on a repo or files |
| `GET` | `/audit/status/{job_id}` | Poll results of a running audit |
| `GET` | `/audit/repos/{owner}/{repo}/tree` | Browse repo file tree |
| `GET` | `/issues/` | List all issues (filter by status/severity/owner) |
| `GET` | `/issues/stats` | Dashboard counts |
| `GET` | `/issues/{id}` | Get single issue |
| `PATCH` | `/issues/{id}` | Update status or reassign owner |
| `DELETE` | `/issues/{id}` | Delete issue from local DB |
| `POST` | `/webhook/github` | GitHub push webhook |

Interactive docs: **http://localhost:8000/docs**

---

## Trigger an Audit

```bash
# Full repo scan
curl -X POST http://localhost:8000/audit/ \
  -H "Content-Type: application/json" \
  -d '{
    "repo": "88gravity/your-repo",
    "branch": "main",
    "park_to_jira": true,
    "park_to_sheet": true
  }'

# Specific files only
curl -X POST http://localhost:8000/audit/ \
  -H "Content-Type: application/json" \
  -d '{
    "repo": "88gravity/your-repo",
    "branch": "main",
    "paths": ["src/auth/login.py", "api/users.js"],
    "park_to_jira": true,
    "park_to_sheet": true
  }'
```

---

## Google Sheets Setup

1. Create a project in [Google Cloud Console](https://console.cloud.google.com)
2. Enable **Google Sheets API** and **Google Drive API**
3. Create a **Service Account** → download JSON key
4. Save JSON to `credentials/google_service_account.json`
5. Share your Google Sheet with the service account email (Editor access)
6. Copy the Sheet ID from the URL into `.env`

---

## GitHub Webhook Setup

1. Go to your repo → **Settings → Webhooks → Add webhook**
2. Payload URL: `https://your-domain.com/webhook/github`
3. Content type: `application/json`
4. Secret: value of `GITHUB_WEBHOOK_SECRET` in `.env`
5. Events: **Just the push event**

Every push will automatically audit all changed files.

---

## Owner Assignment Logic

Priority order for each file:
1. **Explicit override** in the audit request (`owner_overrides` field)
2. **Path prefix rule** — configure in `app/services/owner_service.py` (e.g. `auth/` → Rahul)
3. **GitHub blame** — last committer of that file
4. **Round-robin** fallback across the team

---

## Follow-up Schedule

- Scheduler runs every hour
- Issues past their `deadline_at` (default 48h) get:
  - Email to the owner
  - Slack message to the channel
  - Comment added to the Jira ticket
  - Follow-up count incremented in Google Sheets
- After **3 follow-ups**: issue status changes to `escalated`

---

## Run Tests

```bash
pytest tests/ -v
```

---

## Project Structure

```
code-auditor-bot/
├── app/
│   ├── main.py                  # FastAPI entry point + lifespan
│   ├── config.py                # Settings via pydantic-settings
│   ├── api/
│   │   ├── audit.py             # POST /audit — trigger + background task
│   │   ├── issues.py            # CRUD for issues
│   │   └── webhooks.py          # GitHub push webhook
│   ├── services/
│   │   ├── github_service.py    # Fetch repo tree + file content
│   │   ├── ai_service.py        # Claude audit API call
│   │   ├── jira_service.py      # Create/close Jira tickets
│   │   ├── sheets_service.py    # Read/write Google Sheets
│   │   ├── owner_service.py     # Assign owners (blame / rules / round-robin)
│   │   └── followup_service.py  # 48h SLA checker + notifications
│   ├── models/
│   │   ├── issue.py             # SQLAlchemy ORM + Pydantic schemas
│   │   └── audit_request.py     # Request schema
│   ├── scheduler/
│   │   └── jobs.py              # APScheduler — runs followup every hour
│   └── db/
│       └── database.py          # SQLite async engine
├── frontend/
│   ├── templates/               # Jinja2 dashboard + issue detail
│   └── static/style.css
├── tests/
│   ├── test_audit.py
│   ├── test_github.py
│   └── test_followup.py
├── credentials/                 # Google service account JSON (gitignored)
├── .env.example
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```
