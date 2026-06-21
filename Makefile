.PHONY: install install-backend install-frontend \
        dev-up dev-stop dev-down \
        api web migrate db \
        lint test test-e2e build audit help

# Local dev infra (Postgres) via compose; api and web run on the host.
# Full containerised stack: docker compose up
COMPOSE := docker compose

# ── Install ───────────────────────────────────────────────────────────────────

install: install-backend install-frontend

install-backend:
	cd backend && pip install -e ".[dev,llm,postgres]"

install-frontend:
	cd frontend && npm install

# ── Local dev infra ───────────────────────────────────────────────────────────

dev-up:
	$(COMPOSE) up -d --wait db
	@echo "Postgres ready"

dev-stop:
	$(COMPOSE) stop

dev-down:
	$(COMPOSE) down -v

# ── Services (host) ───────────────────────────────────────────────────────────

api:
	cd backend && uvicorn app.main:app --reload --port 8000

web:
	cd frontend && npm run dev

# ── Database ──────────────────────────────────────────────────────────────────

migrate:
	cd backend && alembic upgrade head

db:
	$(COMPOSE) exec db psql -U booking -d booking

# ── Quality ───────────────────────────────────────────────────────────────────

lint:
	cd backend && ruff check app tests
	cd frontend && npm run lint && npm run typecheck

test:
	cd backend && pytest --cov=app --cov-report=term-missing
	cd frontend && npm run test:cov

test-e2e:
	cd frontend && npm run test:e2e

build:
	cd frontend && npm run build

audit:
	cd frontend && npm run security:audit

# ── Help ──────────────────────────────────────────────────────────────────────

help:
	@echo "install          install backend + frontend dependencies"
	@echo "dev-up           start Postgres in Docker (waits for healthcheck)"
	@echo "dev-stop         stop compose services"
	@echo "dev-down         stop compose services and remove volumes"
	@echo "migrate          alembic upgrade head"
	@echo "api              run backend dev server on :8000 (host)"
	@echo "web              run frontend dev server on :3000 (host)"
	@echo "db               open psql shell into the compose Postgres"
	@echo "lint             ruff check + eslint + tsc --noEmit"
	@echo "test             pytest (100% cov gate) + vitest --coverage"
	@echo "test-e2e         Playwright end-to-end tests"
	@echo "build            Next.js production build"
	@echo "audit            npm audit (prod deps, high+ severity)"
