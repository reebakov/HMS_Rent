.PHONY: up down logs build dev-backend dev-worker dev-frontend migrate test test-frontend test-frontend-cov test-down

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

# Тесты бэкенда в Docker (отдельная БД в tmpfs). Пример: make test ARGS="-k booking -x"
test:
	docker compose -f docker-compose.test.yml run --rm --build tests $(ARGS)

# Тесты и проверка типов фронтенда в Docker (Node на хосте не нужен)
test-frontend:
	docker run --rm --user "$$(id -u):$$(id -g)" -e npm_config_cache=/tmp/.npm -v "$(CURDIR)/frontend:/app" -w /app node:20-alpine \
		sh -c "npm install --no-audit --no-fund && npm run test -- $(ARGS) && npm run typecheck"

# Покрытие фронтенда (текстовый отчёт + frontend/coverage/lcov.info)
test-frontend-cov:
	docker run --rm --user "$$(id -u):$$(id -g)" -e npm_config_cache=/tmp/.npm -v "$(CURDIR)/frontend:/app" -w /app node:20-alpine \
		sh -c "npm install --no-audit --no-fund && npm run test:coverage"

test-down:
	docker compose -f docker-compose.test.yml down -v
