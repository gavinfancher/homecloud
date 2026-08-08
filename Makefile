.PHONY: install test build dev-api dev-web deploy-web deploy-stack deploy-remote smoke

COMPOSE_FILE := infra/docker/docker-compose.yml
COMPOSE := docker compose -p homecloud -f $(COMPOSE_FILE) --env-file .env

install:
	.venv/bin/pip install -e '.[dev]'
	npm --prefix frontend install

test:
	.venv/bin/pytest -q
	npm --prefix frontend run lint
	npm --prefix frontend run build

build:
	$(COMPOSE) build controller
	npm --prefix frontend run build

dev-api:
	.venv/bin/uvicorn homecloud.main:app --reload --host 0.0.0.0 --port 8080

dev-web:
	npm --prefix frontend run dev

# Backup web deploy — the primary path is Cloudflare Workers Git on push to main.
deploy-web:
	npm --prefix frontend/gavinf-prod run build
	npx --prefix frontend/gavinf-prod wrangler deploy -c frontend/gavinf-prod/wrangler.toml

deploy-stack:
	./scripts/deploy-stack.sh

deploy-remote:
	./scripts/deploy-remote.sh

smoke:
	curl -fsS http://localhost:8080/api/health
	curl -fsS http://localhost:8080/api/sizes >/dev/null
	@echo "smoke ok"
