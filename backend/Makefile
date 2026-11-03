# Local shortcuts. The cluster is deployed by CI + Argo CD, not from here.
TEST_DB ?= postgresql://postgres:test@localhost:5434/postgres
DEMO_DB = postgresql://postgres:test@localhost:5434/demo

dev:
	docker compose up --build

test:
	@docker ps --format '{{.Names}}' | grep -qx homecloud-testdb || \
	  docker run -d --rm --name homecloud-testdb -e POSTGRES_PASSWORD=test -p 127.0.0.1:5434:5432 postgres:18.4 >/dev/null
	@until docker exec homecloud-testdb pg_isready -q; do sleep 1; done
	HOMECLOUD_TEST_DATABASE_URL=$(TEST_DB) uv run pytest -q

# The UI against a pretend Proxmox: http://localhost:8010, no sign-in, nothing real touched.
demo:
	@docker ps --format '{{.Names}}' | grep -qx homecloud-testdb || \
	  docker run -d --rm --name homecloud-testdb -e POSTGRES_PASSWORD=test -p 127.0.0.1:5434:5432 postgres:18.4 >/dev/null
	@until docker exec homecloud-testdb pg_isready -q; do sleep 1; done
	@# Its own database, so `make test` (which empties the test one) doesn't wipe it mid-demo.
	@docker exec homecloud-testdb psql -qU postgres -c 'DROP DATABASE IF EXISTS demo WITH (FORCE)' -c 'CREATE DATABASE demo'
	HOMECLOUD_LOCAL=1 HOMECLOUD_FAKE_PROXMOX=1 HOMECLOUD_DATABASE_URL=$(DEMO_DB) \
	HOMECLOUD_STATIC_DIR=../frontend/static HOMECLOUD_PROXMOX_UI=http://localhost:8010/static \
	HOMECLOUD_SSH_KEYS="ssh-ed25519 AAAAdemo demo" HOMECLOUD_WINDOWS_ADMIN_PASSWORD=demo \
	uv run uvicorn app.main:app --port $${PORT:-8010} --reload --reload-dir app

password-hash:
	uv run python -m app.auth

logs:
	kubectl -n homecloud logs -f deploy/homecloud

.PHONY: dev demo test password-hash logs
