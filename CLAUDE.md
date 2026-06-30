# Fabrikam Single-Customer-View — Project Conventions

Scenario 3 (Data Engineering): seven source systems → one trustworthy customer.

This file is the contract for how Claude Code works in this repo. Three
levels operate together: this **root** file (overall pattern), **per-zone**
files under `warehouse/<zone>/CLAUDE.md` (what differs about raw vs.
conformed vs. curated), and the engineer's **user-level** file (personal
preferences). When asked to write to a zone, read its local file first.

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

- **Per-zone `CLAUDE.md` first.** `warehouse/<zone>/CLAUDE.md` carries the local mutation/retention/PII rules. Read it before writing to that zone.
- **Hooks for guardrails, prompts for preferences.** Quality contracts are Python code enforced by `.claude/hooks/curated_gate.sh` (PreToolUse, blocks Writes into `warehouse/curated/` when contracts are red). Zone semantics and conventions live in prompts and these CLAUDE.md files. This split is intentional and lives in the ADR.
- **The matcher is the only probabilistic component.** Everything else is deterministic code. If you find yourself asking Claude to "be careful" with a quality check, you've put the check in the wrong place — move it to `pipeline/quality.py`.
- **Few-shot with a negative case.** `backend/tests/golden_pairs.csv` includes deliberate negatives (Sean Williams ≠ Sean Rodriguez; Jurgen Schmidt Berlin ≠ Köln). Two sharp boundary examples beat a paragraph of "be conservative."
- **API contract is the truth source.** Change it in `backend/api/main.py`, regenerate the TS types with `make types`. Frontend mock data in `frontend/src/api/mock.ts` follows the same shapes.

## Refusal and escalation patterns

- **Refuse to silently coerce.** A date that won't strict-parse and won't dateutil-parse goes to `conformed._reject` with `reject_reason` and `reject_field`. It does **not** become `None` quietly. The eval harness counts rejects as evidence.
- **Refuse to write past a red contract.** If the curated-gate hook blocks a Write, do not disable the hook to make progress. Fix the failing check or update the contract.
- **Escalate via the review queue, not via guessing.** Pairs in the 0.70–0.89 confidence band go to `curated.customer_review` for human decision. Do not auto-merge to clear the queue.

## Tools

A separate MCP server (`mcp/`) exposes six lineage-and-preview tools (`list_sources`, `preview_table`, `find_record`, `trace_lineage`, `get_source_schema`, `quality_status`). When investigating a bad value in a report, prefer those tools over ad-hoc SQL — they encode the right shape of a trace.
