# Fabrikam Single-Customer-View — Project Conventions

Scenario 3 (Data Engineering): seven source systems → one trustworthy customer.

## Stack at a glance

- **Backend** — Python 3.11+, DuckDB (lakehouse), Polars, FastAPI, rapidfuzz, phonenumbers, pytest.
  Lives in `backend/`. Run `make pipeline` to ETL, `make api` for the REST server.
- **Frontend** — React 18 + Vite + TypeScript, Tailwind CSS, TanStack Query, Recharts.
  Lives in `frontend/`. Run `make web`. A mock-mode (`VITE_MOCK=1`) returns canned data so the
  frontend builds and demos even without the backend up.
- **Warehouse** — single DuckDB file at `warehouse/fabrikam.duckdb` (gitignored).

`make dev` starts both API (`:8000`) and Web (`:5173`) concurrently.

## Repo layout

```
backend/
  pipeline/           ingest / conform / match / quality / schemas / normalize / run
  api/                FastAPI app (CORS open to :5173, OpenAPI at /docs)
  tests/              pytest + matcher eval harness (Challenge 7)
frontend/
  src/
    pages/            SwampDashboard, GoldenRecord, StewardshipQueue, LineageTrace
    api/              typed client + mock layer
    components/
decisions/            ADRs. ADR-0001 is the architecture.
docs/                 the-mess.md, catalog/
warehouse/            DuckDB file (gitignored)
acq_*, crm, …         Source files. DO NOT EDIT. Treat as read-only inputs.
```

## Three zones — the rule of thumb

| Zone        | Mutation rule                       | Retention   | PII policy                       | Who reads it          |
|-------------|-------------------------------------|-------------|----------------------------------|-----------------------|
| `raw`       | Append-only / truncate-and-reload   | Indefinite  | Verbatim from source             | Data engineers only   |
| `conformed` | Idempotent rebuild from raw         | 7 years     | Normalized but unhashed          | DEs + senior analysts |
| `curated`   | Idempotent rebuild from conformed   | 7 years     | Email/phone hashed, street tokenized | Analysts, BI, app    |

Each zone has its own `CLAUDE.md` under `warehouse/<zone>/`. Read it before writing to that zone.

## Hard rules

- **Source files are read-only.** Fixes go into the conformed layer, never by editing files under `acq_*/`, `crm/`, etc.
- **Lineage on every raw row:** `_source`, `_source_file`, `_source_row`, `_ingested_at`, `_raw_payload` (JSON). Losing this means we can't honor Challenge 8 (The Trace).
- **No raw PII in `curated`.** Email and phone get SHA-256 with a peppered salt; full street tokenized.
- **Idempotency.** Re-running any `pipeline/*.py` produces the same warehouse state. If it doesn't, that's a bug.
- **Validation-retry on parsing**, not silent coercion. Rows whose strict parse fails fall back to dateutil; if that also fails, the row goes to `conformed._reject` with the specific failed field and reason.

## Conventions

- Identifiers in the warehouse are `snake_case`. Source-side identifiers stay verbatim under `_raw_payload`.
- Surrogate keys: `customer_id` is `uuid5(NS, normalized_email | phone | name+dob)` so reruns are stable.
- Confidence is a float in `[0,1]` with thresholds: `>=0.90` auto-merge, `0.70-0.89` review queue, `<0.70` separate.
- Timezones: store UTC. Source TZ recorded as `_source_tz`; if unknown, `'UNKNOWN'` — don't invent.

## Working with Claude Code in this repo

- Per-zone `CLAUDE.md` files at `warehouse/<zone>/CLAUDE.md`. When asked to write to a zone, read its `CLAUDE.md` first.
- Quality checks are **deterministic guardrails**. They live in Python, not in prompts. The matcher is the only probabilistic component.
- Few-shot examples for the matcher live in `backend/tests/golden_pairs.csv`. Two sharp boundary cases beat a paragraph of "be conservative."
- API contract is the truth source between backend and frontend. Change it in `backend/api/main.py`, regenerate the TS types (`make types`).
