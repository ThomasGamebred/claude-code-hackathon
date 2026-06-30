# Team SCV-Swampers

## Participants

- TBD (architect / data engineer)
- TBD (backend / matcher)
- TBD (frontend)
- TBD (quality / hooks)
- TBD (catalog / docs)
- TBD (eval / CI)

> Placeholder names. Rename before submission.

## Scenario

**Scenario 3 — Data Engineering: Single Customer View.** Fabrikam Retail has
seven source systems that disagree on what a customer is. Same person, four
IDs, two spellings, one mojibake'd umlaut. The CDO wants one trustworthy
record. We picked a lakehouse architecture, a deterministic-plus-fuzzy
matcher, and a React frontend that lets you actually *see* the mess collapse
into a golden record.

## What We Built

A three-zone lakehouse on a single DuckDB file (`warehouse/fabrikam.duckdb`).
Seven loaders land each source verbatim in the **raw** zone with full
lineage columns (`_source`, `_source_file`, `_source_row`, `_ingested_at`,
`_raw_payload`). A conform layer rebuilds the **conformed** zone with a
canonical schema, pure normalizers (Excel-serial dates, E.164 phones,
encoding heuristics, ZIP padding), and a validation-retry loop that sends
unsalvageable rows to `_reject` with a specific reason. The **curated** zone
holds `customer_master`, `customer_xref`, `match_audit`, and
`customer_review`. PII is hashed on the way in.

The matcher in `backend/pipeline/match.py` is two-pass: deterministic merges
on strong keys (normalized email, E.164 phone, cross-source FKs), then a
fuzzy pass with `rapidfuzz` over `(name, street, city)` blocked by
`(last_initial, region, birth_year)`. Survivorship is field-level and
explicit — every field on the master row carries a source attribution and a
confidence. A record-level confidence drives three lanes: `>=0.90`
auto-merge, `0.70-0.89` to the stewardship queue, `<0.70` stays separate.

The frontend (React 18 + Vite + TypeScript + Tailwind + TanStack Query)
exposes four pages: the **Swamp Dashboard** (per-source counts, quality
scores, last-ingest timestamp), the **Golden Record viewer** (master row
plus all source rows with field-level confidence), the **Stewardship Queue**
(the 0.70-0.89 band, with side-by-side diff and Merge/Keep-separate
buttons), and the **Lineage Trace** (curated -> xref -> conformed -> raw
-> the original `_raw_payload`). The eval harness in
`backend/tests/test_matcher_eval.py` runs against `golden_pairs.csv` and
reports precision, recall, and false-confidence rate stratified by
easy/hard/boundary/negative — runs in CI so the CDO gets a defensible
single number. See [`decisions/ADR-0001-blueprint.md`](decisions/ADR-0001-blueprint.md)
for the full architecture write-up.

## Challenges Attempted

| # | Challenge | Status | Notes |
|---|---|---|---|
| 1 | The Mess | done | Realistic noise already lives in `acq_*/`, `crm/`, `pos/`, `loyalty/`, `ecommerce/`. Inventory documented in [`docs/the-mess.md`](docs/the-mess.md). |
| 2 | The Blueprint | done | Three-zone lakehouse, three-level CLAUDE.md, "what we chose not to do" section. ADR-0001. |
| 3 | The Intake | done | 7 source loaders, all with lineage columns. Validation-retry on date parsing (strict -> dateutil -> reject). CDC/flaky-API stubs not built (see below). |
| 4 | The Customer | done | Two-pass matcher, field-level survivorship, explicit thresholds. |
| 5 | The Tripwire | done | Schema drift (BLOCK), null explosion / volume / RI (ALERT). `PreToolUse` hook in `.claude/hooks/curated_gate.sh`. |
| 6 | The Catalog | done | `docs/catalog/customer.md` and `docs/catalog/sources.md`. Analyst-readable, linked to ADR-0001 §3. |
| 7 | The Scorecard | done | 20+ stratified pairs, precision / recall / false-confidence-rate, in CI. |
| 8 | The Trace | partial | Lineage path is in the API and rendered on the frontend. No MCP server yet — that's "if we had more time". |
| 9 | The Swarm | skipped | Designed it on paper as per-source Task subagents emitting structured profile reports; ran out of clock to wire it. |

## Key Decisions

- **DuckDB as the lakehouse.** Lakehouse semantics in a single file, demo-able
  on a laptop. We accept that this caps us at one host.
- **Hooks for guardrails, prompts for preferences.** Quality contracts are
  Python code enforced by a `PreToolUse` hook; zone semantics live in
  per-zone `CLAUDE.md` files.
- **Mock-mode frontend (`VITE_MOCK=1`).** Frontend was never blocked on the
  backend during the hack.
- **Explicit survivorship.** No "last wins" magic. Every field has a rule
  and a confidence.

Full write-up in [`decisions/ADR-0001-blueprint.md`](decisions/ADR-0001-blueprint.md).

## How to Run It

**Preferred — with `make`:**

```bash
make setup      # pip install -e ./backend[dev] + npm install in frontend/
make pipeline   # ETL all 7 sources into warehouse/fabrikam.duckdb
make dev        # backend on :8000, frontend on :5173, Ctrl-C kills both
```

**Open** http://localhost:5173 and you should see the Swamp Dashboard.

**Backup route — no make (Windows PowerShell or any POSIX shell):**

```bash
pip install -e "./backend[dev]"
cd frontend && npm install && cd ..
cd backend && python -m pipeline.run && cd ..

# in one terminal:
cd backend && uvicorn api.main:app --reload --port 8000
# in another terminal:
cd frontend && npm run dev
```

**Tests:**

```bash
make test
# or
cd backend && pytest -q
```

**OS notes.** The Makefile is POSIX-shell; on Windows use **Git Bash** or
**WSL** so `make` and `bash -c` are available. msys2's `make` ships with
Git for Windows by default. PowerShell-native users should use the backup
route above. macOS / Linux: nothing special.

## Architecture

```
sources/                raw                 conformed             curated              API           Web
                                                                                                    
acq_northwind  ┐                                                                                    
acq_rheinland  │                                                                                    
acq_sunset     │       one table          customer  (canonical    customer_master                   
crm            ├──►    per source   ──►   schema, normalized) ──► customer_xref      ──►  FastAPI  ──►  React
ecommerce      │       + lineage          _reject                  match_audit         (OpenAPI)   (Vite/TS)
loyalty        │       columns            (rejects w/ reason)      customer_review                  
pos            ┘                                                                                    
                                                                                                    
                       append-only       idempotent rebuild       idempotent rebuild   /api/...    pages/
                                                                  PII hashed                       Swamp
                                                                                                   Golden
                                                                                                   Stewardship
                                                                                                   Lineage
```

## If We Had More Time

In priority order:

1. **MCP server for trace tools (Challenge 8).** `preview_table`,
   `trace_lineage`, `find_record`, `get_source_schema` over the curated
   warehouse. A fresh Claude session should pick the right tool first try.
2. **Streaming ingestion.** Today every source is batch. Add a CDC stream
   shape (POS) and a flaky-API shape (loyalty) with backoff + retry budget.
3. **Stewardship UI persistence.** Today the review buttons log the
   decision but the matcher doesn't re-evaluate in-place. Wire it through.
4. **KMS-backed PII hashes.** The salt is currently `DEMO_ONLY` in the
   repo. Move it to an envelope-encrypted key.
5. **Address standardization.** We rely on rapidfuzz; USPS/CASS would lift
   recall on the boundary band.
6. **Multi-tenancy.** Today everything is global. Tenant-scoped tables and
   row-level filters in the API.
7. **The Swarm (Challenge 9).** Per-source profiling subagents that emit
   structured reports, aggregated into a "swamp health" dashboard.

## How We Used Claude Code

- **Subagents for parallel build.** Six person-roles in `plan.md` map to
  six Claude Code subagents working in parallel branches. Coordinator
  passed each one a tight context envelope: the ADR, the per-zone
  CLAUDE.md, the API contract.
- **Hooks for the curated-zone gate.** `.claude/hooks/curated_gate.sh`
  fires on `PreToolUse` for `Write` calls under `warehouse/curated/`. If
  `quality.assert_contracts_pass()` is red, the write is blocked. This is
  the cleanest split between deterministic guardrails (hooks) and
  probabilistic preferences (prompts).
- **Three-level CLAUDE.md.** Root file at `CLAUDE.md` carries the project
  conventions. Per-zone files under `warehouse/<zone>/CLAUDE.md` carry the
  things that differ (mutation rule, PII policy, retention). User-level
  is the engineer's personal preferences.
- **Eval harness in CI.** `backend/tests/test_matcher_eval.py` runs on
  every PR. Precision, recall, false-confidence rate, stratified — one
  defensible number for the CDO.
- **Validation-retry loop on date parsing.** Strict format -> dateutil
  fallback -> reject row with `reject_reason` + `reject_field`. Logged
  retry counts become evidence in the catalog.

---

`presentation.html` lives at the repo root.
