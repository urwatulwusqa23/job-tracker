# Hired — AI Job Tracker

A self-hosted web app for tracking job applications end-to-end, powered by xAI's Grok. Built with Flask + SQLite, deployable in a single Docker command.

## Features

- **Kanban board** — track applications across Applied / Screening / Interview / Offer / Rejected / Withdrawn
- **AI import** — paste any email or WhatsApp message and Grok extracts company, role, salary, location, and job URL automatically
- **Gmail scan** — connect via App Password to scan your inbox for job-related emails and import them in one click
- **Interview prep** — generates 5 technical questions, 5 behavioural questions, salary negotiation advice, company research points, and a personalised tip — all based on your CV and the job description
- **Skills gap analysis** — compares your CV against jobs you've applied for and returns skill gaps, ranked courses, projects to build, certifications to pursue, and 2025 market insights
- **Job recommendations** — pulls live remote listings from Remotive matched to keywords derived from your CV; one-click track any result
- **CV manager** — upload multiple PDF CVs, set one as active; all AI features use the active CV automatically
- **Activity feed** — timestamped log of every status change and AI action

## Quick start (local)

**Prerequisites:** Python 3.11+, pip

```bash
git clone <your-repo-url>
cd job-tracker

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env and add your XAI_API_KEY
```

Get a free xAI API key at [console.x.ai](https://console.x.ai) — xAI provides generous free monthly tokens.

```bash
python app.py
```

Open `http://localhost:5001`

## Quick start (Docker)

```bash
cp .env.example .env
# Edit .env and add your XAI_API_KEY

docker compose up -d
```

Open `http://localhost:8080`

Data is persisted in a named Docker volume (`job_data`) so it survives container restarts.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `XAI_API_KEY` | *(required for AI features)* | xAI API key from console.x.ai |
| `GROK_MODEL` | `grok-3-mini` | Model to use — `grok-3` or `grok-2` for more power |
| `DB_PATH` | `jobtracker.db` | Path to the SQLite database file |
| `PORT` | `5001` (local) / `8080` (Docker) | Port the server listens on |

AI features (import, interview prep, skills gap, job recommendations) all require `XAI_API_KEY`. The app runs fine without it — you can still manually add and manage applications.

## Deployment

### Render.com (free tier)

1. Push this repo to GitHub
2. Create a new **Web Service** on [render.com](https://render.com), connect your repo
3. Render auto-detects `render.yaml` and configures everything
4. Set `XAI_API_KEY` in the Render dashboard under **Environment**

> **Note:** The free Render tier has no persistent disk — data resets on each deploy/restart. Upgrade to the Starter plan ($7/mo) and add a Disk mounted at `/data` for persistence.

### Fly.io

A `fly.toml` is included. After installing the [Fly CLI](https://fly.io/docs/hands-on/install-flyctl/):

```bash
fly launch   # first time
fly deploy   # subsequent deploys
fly secrets set XAI_API_KEY=xai-your-key-here
```

### Any VPS / Docker host

```bash
docker compose up -d
```

Point a reverse proxy (nginx, Caddy) at port 8080.

## Gmail scan setup

The Gmail scan uses IMAP with an App Password — not your regular Google password.

1. Go to your Google Account → **Security** → **2-Step Verification** (must be enabled)
2. Search for **App Passwords** → create one for "Mail"
3. Enter your Gmail address and the 16-character App Password in the Import tab

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, Flask 3 |
| AI | xAI Grok (via OpenAI-compatible API) |
| Database | SQLite (via `sqlite3`) |
| PDF parsing | pdfplumber |
| Server | Gunicorn (2 workers, 120s timeout) |
| Frontend | Vanilla JS + CSS (no build step) |
| Container | Docker / Docker Compose |

## Project structure

```
job-tracker/
├── app.py              # Flask app — all routes and business logic
├── templates/
│   └── index.html      # Single-page frontend (HTML + CSS + JS)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── render.yaml         # Render.com deployment config
├── fly.toml            # Fly.io deployment config
├── .env.example        # Environment variable template
└── .gitignore
```

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/stats` | Dashboard stats and recent activity |
| `GET` | `/api/applications` | List all applications |
| `POST` | `/api/applications` | Add an application |
| `PUT` | `/api/applications/<id>` | Update an application |
| `DELETE` | `/api/applications/<id>` | Delete an application |
| `GET` | `/api/cv` | List uploaded CVs |
| `POST` | `/api/cv` | Upload a CV (PDF) |
| `POST` | `/api/cv/<id>/activate` | Set a CV as active |
| `GET` | `/api/cv/<id>/download` | Download a CV |
| `GET` | `/api/cv/active_text` | Get extracted text from active CV |
| `POST` | `/api/extract_job` | AI-extract job details from pasted text |
| `POST` | `/api/gmail_scan` | Scan Gmail inbox for job emails |
| `GET` | `/api/interview_prep/<id>` | Get saved interview prep for an application |
| `POST` | `/api/interview_prep/<id>` | Generate new interview prep |
| `POST` | `/api/skills_gap` | Analyse CV against applied jobs |
| `POST` | `/api/job_recommendations` | Fetch live job listings matched to CV |
