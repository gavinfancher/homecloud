.PHONY: install test build dev-api dev-web deploy-frontend deploy-stack smoke

install:
	.venv/bin/pip install -e '.[dev]'
	npm --prefix frontend install

test:
	.venv/bin/pytest -q
	npm --prefix frontend run lint
	npm --prefix frontend run build

build:
	docker compose build controller
	npm --prefix frontend run build

dev-api:
	.venv/bin/uvicorn homecloud.main:app --reload --host 0.0.0.0 --port 8080

dev-web:
	npm --prefix frontend run dev

deploy-frontend:
	./scripts/deploy-frontend.sh

deploy-stack:
	./scripts/deploy-stack.sh

smoke:
	curl -fsS http://localhost:8080/api/health
	curl -fsS http://localhost:8080/api/sizes >/dev/null
	@echo "smoke ok"
