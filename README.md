# Booking Workflow

A multi-agent booking workflow that turns a single chat message into a confirmed
booking. A human approval step runs before any mutation, and the UI shows the
workflow as it executes.

> *"Create a booking for John Doe for contact work on June 20 at 10am. Email
> john@example.com, phone 0400000000, address 12 Queen St Brisbane."*

A **LangGraph** supervisor orchestrates specialist agents for extraction,
validation, customer lookup, availability, planning, risk review, approval,
execution, email, audit, and memory. An **LLM** can parse the free-text request,
with a deterministic fallback for local development. Booking data lives in this
app's own database. Every node streams its status over **SSE** to a read-only
**React Flow** canvas.

## Features

- **Multi-agent orchestration**: a LangGraph supervisor graph routes between
  specialist agents; each is independently testable and instrumented.
- **Human-in-the-loop**: the graph pauses at approval via LangGraph
  `interrupt()` + a checkpointer, then resumes on approve/reject. No mutation
  runs before approval.
- **LLM extraction with a safety net**: OpenAI structured-output parsing, with a
  deterministic rule parser as a fallback so it never hard-fails.
- **Bounded availability search**: a sub-graph loops over staff/days (≤3
  attempts, ≤7-day window) to find and rank alternative slots.
- **Cleaner selection**: the chosen cleaner is scored on **skill match**
  (can they do the service?), **workload** (balance the team), and **proximity**
  (home base → job, Haversine). The pick is deterministic + auditable; an
  optional LLM one-liner explains *why* on the approval card.
- **Long-term memory**: durable customer facts (preferences, comms, VIP) are
  saved and reloaded on the next run; logs/tool-output are never stored.
- **Live visualization**: node statuses stream over SSE to a React Flow canvas
  as they execute.

### The agents

| Agent | Role |
|---|---|
| `extract_booking_request` | LLM (or rules) → structured booking request |
| `validation_agent` | Hard business rules (required fields, valid email, future date) |
| `customer_agent` | Loads long-term memory; derives the requested slot |
| `availability_subgraph` | Finds/ranks free staff slots; bounded retry loop |
| `job_planning_agent` | Plan the job + pick the best cleaner (skill / load / proximity) |
| `risk_review_agent` | Flag risk (out-of-hours, unassigned) before approval |
| `human_approval` | **Pauses** for a human; prepares (not executes) mutations |
| `execution_agent` | The only mutator; books client/contact/job/appointment |
| `hubspot_agent` | Push the customer contact to HubSpot CRM (post-approval, before payment) |
| `email_agent` | SMTP confirmation email + calendar invite |
| `audit_log` / `memory_agent` | Immutable audit trail; save durable customer facts |

### Architecture

| Layer | Tech |
|---|---|
| Frontend | Next.js (App Router), shadcn/ui + Tailwind, React Flow, TanStack Query, react-hook-form, lucide-react |
| Backend | FastAPI, LangGraph (checkpointed; `interrupt()` for approval) |
| Persistence | PostgreSQL via SQLAlchemy + Alembic |
| Live updates | SSE over an in-process event bus |
| Booking datastore | Local DB: staff, clients, contacts, jobs, appointments |
| Integrations | OpenAI (extraction), HubSpot (CRM contact sync), SMTP (confirmation email + ICS) |

**Conventions:** layered (router → service → repository) with FastAPI DI,
pydantic-settings, custom exceptions + global handlers, correlation-id +
security-headers middleware, API versioning (`/api/v1`), `/api/v1/health[/ready]`,
Ruff lint/format.

## Quickstart

```bash
cp .env.example .env        # optional: fill in OpenAI / SMTP keys
docker compose up --build
```

- Web UI: http://localhost:3000 · API docs: http://localhost:8000/docs

With no keys set it runs fully in **dry-run** mode with rule-based extraction,
database booking, and dry-run email. No external services are required.

## Local development

Requires Python 3.11+ and Node 22+. Postgres runs in Docker; the API and web
server run on the host.

```bash
make install   # pip install -e ".[dev,llm,postgres]" + npm install
make dev-up    # docker compose up -d --wait db (Postgres)
make migrate   # alembic upgrade head
```

Optional demo data (returning customer, occupied schedule, saved preferences):

```bash
cd backend && python -m app.seeds
```

Then in separate terminals:

```bash
make api       # uvicorn app.main:app --reload --port 8000
make web       # npm run dev  →  http://localhost:3000
```

Drop into the database:

```bash
make db        # psql -U booking -d booking
```

Full target list: `make help` or see [Makefile](Makefile).

## API / Usage

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/runs` | Start a booking run (async, 202) |
| GET | `/api/v1/runs/{id}` | Run status + approval card |
| POST | `/api/v1/runs/{id}/approve` · `/reject` | Resolve the human gate |
| GET | `/api/v1/runs/{id}/events` | SSE stream of live node statuses |
| GET | `/api/v1/health` · `/health/ready` | Liveness / readiness |

**1. Start a run** (returns immediately; the agents run in the background):

```bash
curl -sX POST localhost:8000/api/v1/runs -H 'content-type: application/json' \
  -d '{"message":"Create a booking for John Doe for contact work on June 20 at 10am. Email john@example.com, phone 0400000000, address 12 Queen St Brisbane."}'
# → 202 {"run_id":"bbb7af95…","status":"running", ...}
```

**2. Watch it live**. This is the SSE stream consumed by the React Flow canvas:

```bash
curl -N localhost:8000/api/v1/runs/<run_id>/events
# data: {"node":"extract_booking_request","status":"success","duration_ms":2}
# data: {"node":"availability_subgraph","status":"success",...}
# data: {"node":"human_approval","status":"waiting_approval",...}
# event: end
```

**3. Inspect the paused run**. Agents have stopped at the approval gate and
prepared (but not executed) the booking:

```jsonc
GET /api/v1/runs/<run_id>
{
  "status": "paused",
  "approval_card": {
    "customer": "John Doe", "service": "contact work",
    "date": "2026-06-20", "time": "09:00", "staff": "Alex Taylor",
    "email": "john@example.com",
    "prepared_actions": [
      {"action": "create_client",  "payload": {...}},
      {"action": "create_contact", "payload": {...}},
      {"action": "create_job",     "payload": {...}},
      {"action": "schedule_job",   "payload": {"date":"2026-06-20","time":"09:00","staff":"Alex Taylor"}}
    ]
  }
}
```

**4. Approve** → the booking is written to the DB, the confirmation email + ICS
invite go out, and the run completes:

```bash
curl -sX POST localhost:8000/api/v1/runs/<run_id>/approve -d '{"by":"ops@example.com"}'
# later: GET /runs/<run_id> →
# {"status":"completed","final_response":"Booking confirmed for John Doe on 2026-06-20 at 09:00. A confirmation email is on its way."}
```

(Reject instead with `POST /runs/<run_id>/reject`; nothing is written.)

## Testing

```bash
make test      # backend: pytest --cov=app (100% gate) + frontend: vitest --coverage
make test-e2e  # Playwright end-to-end (mocked API, production build)
make lint      # ruff check + eslint + tsc --noEmit
make audit     # npm audit --omit=dev --audit-level=high
```

## Configuration

See [`.env.example`](.env.example). OpenAI and SMTP degrade to safe local
stand-ins when their keys are absent; booking mutations always write to the
local database (default staff seeded on startup so jobs can be assigned).

| Variable | Effect |
|---|---|
| `OPENAI_API_KEY` | Real LLM extraction + embeddings (else deterministic rules) |
| `HUBSPOT_ACCESS_TOKEN` | Push the contact to HubSpot CRM (else dry-run) |
| `FEATURE_HUBSPOT_SYNC` | `false` forces HubSpot dry-run even with a token (standalone testing) |
| `SMTP_HOST` + `MAIL_FROM` | Real SMTP confirmation email (else dry-run) |
| `LANGSMITH_API_KEY` | LangSmith tracing of LLM calls (else off) |
| `BUSINESS_OPEN_HOUR` / `CLOSE_HOUR` | Availability search window |
| `CORS_ORIGINS`, `ENVIRONMENT` | CORS allow-list (defaults to the local frontend; a `*` wildcard is rejected in `production` and never paired with credentials); `production` also hides docs |
| `API_AUTH_TOKEN` | When set, every `/runs` call requires `Authorization: Bearer <token>`, and the authenticated principal, not a client-supplied `by`, is recorded as the approver. Unset → open (dev). |
| `RATE_LIMIT_RUNS` / `RATE_LIMIT_WINDOW_S` | In-process per-client rate limit on run submission (`0` disables) |
| `LOG_LEVEL` | Root log level |
| `DB_POOL_*` / `DB_STATEMENT_TIMEOUT_MS` | Connection pool sizing + a server-side per-query timeout |

**Prompts** are versioned in-repo in [`app/core/prompts.py`](backend/app/core/prompts.py)
(golden-tested). LangSmith is used **only for tracing/observability**, not prompt
storage.

### Wiring OpenAI

1. `pip install -e ".[llm]"` (pulls `langchain-openai` + `openai`).
2. Put your key in `.env`: `OPENAI_API_KEY=sk-...` (optionally `OPENAI_MODEL`,
   `EMBEDDING_MODEL`).
3. `Settings.use_real_openai` flips on: extraction uses the model (rules stay the
   fallback), the cleaner choice gets an LLM rationale, and cleaner bios + the
   customer preference are embedded for semantic matching. With **no** key
   everything degrades to the deterministic path, so tests and offline dev never
   need a secret.

## License

MIT. See [LICENSE](LICENSE).
