# Fabrikam Single-Customer-View — top-level Makefile
#
# Works on Linux, macOS, and Windows under Git Bash (msys2 ships `make`).
# All recipes shell out via /bin/sh, so we stick to POSIX-portable syntax.
# Where bash-specific behaviour is needed we invoke `bash -c` explicitly.
#
# `make dev` runs the API and Web servers in parallel by backgrounding them
# from a single shell and trapping EXIT to clean both up — chosen over
# `make -j2` because `make -j2` doesn't propagate Ctrl-C cleanly under
# Git Bash on Windows, and we want one terminal, two processes, one trap.

.DEFAULT_GOAL := help

.PHONY: help setup pipeline api web dev test clean types

help:  ## list available targets
	@echo "Fabrikam SCV — make targets"
	@echo ""
	@echo "  setup     install python (editable) + node deps"
	@echo "  pipeline  run ETL: raw -> conformed -> curated into warehouse/fabrikam.duckdb"
	@echo "  api       start FastAPI on :8000 with --reload"
	@echo "  web       start Vite dev server on :5173"
	@echo "  dev       start api + web together (Ctrl-C kills both)"
	@echo "  test      run backend pytest suite"
	@echo "  types     regenerate frontend TS types from backend OpenAPI (best-effort)"
	@echo "  clean     remove warehouse db, frontend build, __pycache__"

setup:  ## install python + node deps
	pip install -e "./backend[dev]"
	cd frontend && npm install

pipeline:  ## run the ETL into warehouse/fabrikam.duckdb
	cd backend && python -m pipeline.run

api:  ## start FastAPI on :8000
	cd backend && uvicorn api.main:app --reload --port 8000

web:  ## start Vite dev server on :5173
	cd frontend && npm run dev

dev:  ## start api + web concurrently, single trap
	@bash -c '\
		set -e; \
		trap "kill 0" EXIT INT TERM; \
		( cd backend && uvicorn api.main:app --reload --port 8000 ) & \
		( cd frontend && npm run dev ) & \
		wait'

test:  ## run backend tests
	cd backend && pytest -q

types:  ## best-effort: regen frontend types from OpenAPI (requires uvicorn + openapi-typescript)
	@bash -c '\
		set -e; \
		if ! command -v python >/dev/null 2>&1; then echo "skip: python missing"; exit 0; fi; \
		if ! cd frontend && command -v npx >/dev/null 2>&1; then echo "skip: npx missing"; exit 0; fi; \
		cd backend && python -c "from api.main import app; import json,sys; sys.stdout.write(json.dumps(app.openapi()))" > /tmp/openapi.json || { echo "skip: openapi export failed"; exit 0; }; \
		cd ../frontend && npx --yes openapi-typescript /tmp/openapi.json -o src/api/generated.d.ts || { echo "skip: openapi-typescript failed"; exit 0; }; \
		echo "wrote frontend/src/api/generated.d.ts"'

clean:  ## remove generated artifacts
	rm -f warehouse/fabrikam.duckdb warehouse/fabrikam.duckdb.wal warehouse/last_run_report.json
	rm -rf frontend/dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
