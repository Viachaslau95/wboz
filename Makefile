POETRY ?= /Users/mac/.local/bin/poetry

.PHONY: install db-up db-down db-logs revision migrate current server bot openapi codestyle

install:
	$(POETRY) install --no-root

db-up:
	docker compose up -d db

db-down:
	docker compose down

db-logs:
	docker compose logs -f db

revision:
	@if [ -z "$(m)" ]; then \
		echo "Usage: make revision m=\"create tracked_items table\""; \
		exit 1; \
	fi
	$(POETRY) run alembic revision -m "$(m)"

migrate:
	$(POETRY) run alembic upgrade head

current:
	$(POETRY) run alembic current

server:
	$(POETRY) run python -m app server

bot:
	$(POETRY) run python -m app bot

openapi:
	$(POETRY) run python -m app openapi

codestyle:
	./codestyle.sh
