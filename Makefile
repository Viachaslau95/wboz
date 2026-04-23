POETRY ?= /Users/mac/.local/bin/poetry

.PHONY: install db-up db-down db-logs revision migrate current server bot openapi codestyle prod-pull prod-migrate prod-up prod-ps helm-lint helm-template helm-upgrade

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

prod-pull:
	docker compose -f docker-compose.prod.yml pull

prod-migrate:
	docker compose -f docker-compose.prod.yml run --rm migrator

prod-up:
	docker compose -f docker-compose.prod.yml up -d db api bot caddy

prod-ps:
	docker compose -f docker-compose.prod.yml ps

helm-lint:
	helm lint deploy/helm/wboz

helm-template:
	helm template wboz deploy/helm/wboz -f deploy/helm/values-prod.example.yaml

helm-upgrade:
	@if [ -z "$(f)" ]; then \
		echo "Usage: make helm-upgrade f=deploy/helm/values-prod.yaml"; \
		exit 1; \
	fi
	helm upgrade --install wboz deploy/helm/wboz --namespace wboz --create-namespace -f "$(f)"
