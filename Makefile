# Fabrikam Customer-360 — one-command lakehouse.
# Assumes python3. Creates a local venv; no Docker, no cloud.
PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: help setup build eval profile dq report clean mcp test

help:
	@echo "make setup    - create venv + install deps"
	@echo "make build    - run the full pipeline raw->conformed->curated"
	@echo "make eval     - score the entity matcher against the golden set (CI gate)"
	@echo "make profile  - run the parallel source-profiling swarm -> swamp dashboard"
	@echo "make dq        - print the data-quality report"
	@echo "make report    - human-readable build report"
	@echo "make test      - unit tests for the normalizers + matcher"
	@echo "make mcp       - run the lineage MCP server (stdio)"

setup:
	python3 -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r requirements.txt pytz tzdata

build:
	$(PY) scripts/run_pipeline.py

eval:
	$(PY) eval/score_matcher.py

profile:
	$(PY) -m pipeline.profile

dq:
	$(PY) -m pipeline.dq

report:
	$(PY) scripts/report.py

test:
	$(PY) -m pytest -q tests/

mcp:
	$(PY) mcp/server.py

clean:
	rm -f warehouse.duckdb warehouse.duckdb.wal
