.PHONY: up down logs build dev-backend dev-worker dev-frontend migrate

# Всё в Docker: http://localhost:8080
up:
	@test -f .env || cp .env.example .env
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f backend worker

# Локальная разработка без Docker (нужен Postgres на localhost:5432)
dev-backend:
	cd backend && alembic upgrade head && uvicorn app.main:app --reload --port 8000

dev-worker:
	cd backend && python -m app.worker

dev-frontend:
	cd frontend && npm install && npm run dev

migrate:
	docker compose exec backend alembic upgrade head
