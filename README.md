# Nova Command Center

Production-ready React + FastAPI dashboard for content operations, revenue tracking, and agent orchestration.

## Stack

- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS, Recharts
- **Backend:** FastAPI, SQLAlchemy 2.0, Alembic, SQLite
- **Infrastructure:** Docker Compose

## Quick Start (Docker)

```bash
cp .env.example .env
docker compose up --build
```

- **App:** http://localhost:3000
- **API docs:** http://localhost:8000/docs
- **Health:** http://localhost:8000/health

## Pages

1. CEO Dashboard — executive overview
2. KPI Dashboard — performance metrics
3. Content Factory — scripts → videos → shorts pipeline
4. Topic Intelligence — trend research and topic management
5. Revenue Center — sponsors and revenue tracking
6. Agent Control Center — AI agent task queue

## Local Development

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt

# Start SQLite database (created automatically at ./data/nova.db)
set DATABASE_URL=sqlite:///./data/nova.db
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Set `VITE_API_URL=http://localhost:8000/api/v1` in `.env` for local dev.

## API Endpoints

Base path: `/api/v1`

| Endpoint | Description |
|---|---|
| `GET /dashboard/ceo` | CEO dashboard aggregates |
| `GET /dashboard/kpi` | KPI metrics |
| `GET /content/pipeline` | Content pipeline view |
| `GET /revenue/summary` | Revenue breakdown |
| `GET /tasks/agents` | Agent task summary |
| `GET/POST /topics` | Topic CRUD |
| `GET/POST /scripts` | Script CRUD |
| `GET/POST /videos` | Video CRUD |
| `GET/POST /shorts` | Short CRUD |
| `GET/POST /sponsors` | Sponsor CRUD |
| `GET/POST /revenue` | Revenue CRUD |
| `GET/POST /tasks` | Task CRUD |
| `GET/POST /users` | User CRUD |

## Database Tables

`users`, `topics`, `scripts`, `videos`, `shorts`, `sponsors`, `revenue`, `tasks`
