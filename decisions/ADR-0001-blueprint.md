# ADR-0001 — Lakehouse Blueprint for the Fabrikam Single-Customer-View

- **Status:** Accepted
- **Date:** 2026-06-30
- **Deciders:** Hackathon team (acting CDO, lead DE, architect)
- **Scope:** Scenario 3 — seven systems, one customer.

## Context

Fabrikam Retail has seven source systems with mutually inconsistent definitions of "customer." Today, every analysis starts from CSV exports and ends in disagreement. The new CDO wants **one** trustworthy view; the team wants something a single engineer can run, demo, and reason about end-to-end in an afternoon.

Constraints that drove the decision:

1. **Reproducible on a laptop.** No cloud accounts, no Airflow, no Spark. A teammate can clone the repo and run `make dev` to land at a golden record.
2. **Evidence-driven.** The pipeline must be re-runnable from raw, so reviewers can rewind and inspect any transformation.
3. **Lineage end-to-end** is a stretch goal (Challenge 8) but the architecture must not foreclose it.
4. **Small PII surface.** Analysts must be able to query curated without ever seeing a raw email.
5. **UX matters.** A backend nobody can see is worth nothing in a 80-minute hack. We ship a React frontend that demos the swamp, the golden record, the stewardship queue, and the lineage.

## Decision

A **three-zone lakehouse** on a single DuckDB file, with Polars/pyarrow for transformation, FastAPI as the read API, and a React/Vite frontend as the demo surface.

```
sources/ ──► raw ──► conformed ──► curated ──► /api  ◄──  React (Vite/TS)
            (immutable)  (canonical)   (golden record)
```

### Zones

| Zone        | Schema                                                    | Mutation rule       | Retention   | PII policy                              |
|-------------|-----------------------------------------------------------|---------------------|-------------|-----------------------------------------|
| `raw`       | One table per source. Columns mirror source.              | Append-only.        | Indefinite. | Stored as-emitted by the source.        |
| `conformed` | `customer` (all sources, common schema), `_reject`.       | Idempotent rebuild. | 7 years.    | Normalized but unhashed.                |
| `curated`   | `customer_master`, `customer_xref`, `match_audit`, `customer_review`. | Idempotent rebuild. | 7 years. | Email/phone SHA-256 (peppered), street tokenized. |

Each zone has its own `CLAUDE.md` (see §6). The root `CLAUDE.md` carries the overall pattern; the per-zone files carry what differs. That's the three-level pattern the hackathon brief calls out.

### Why DuckDB

- Lakehouse semantics (columnar, parquet-friendly, SQL on files) without infrastructure.
- One file → trivial to demo, snapshot, and reset.
- Strong CSV/JSON ingest and excellent type-coercion error messages — exploited by our validation-retry loop.
- We accept that this does not scale beyond a single host (§3).

### Why FastAPI + React (not server-rendered)

- The demo story has four screens: Swamp Dashboard, Golden Record, Stewardship Queue, Lineage. They share a backend; they are not server-rendered pages with different layouts.
- FastAPI gives us OpenAPI for free → we generate the TS client and avoid backend/frontend drift.
- Frontend has a **mock mode** (`VITE_MOCK=1`) so it boots before the backend is ready — frontend devs are not blocked by backend devs in Phase 1.

### Ingestion shapes (Challenge 3)

Three deliberately different shapes, one runner pattern:

- **Batch file**: `acq_northwind/legacy_customers.txt` (pipe), `acq_rheinland/kunden.csv` (mojibake), `acq_sunset/catalog_customers.csv` (Excel-serial dates, embedded newlines), `loyalty/loyalty_members.csv`.
- **API-like JSON**: `ecommerce/customers.json`.
- **POS export**: `pos/pos_export_2023-11.csv` (truncated zips, duplicates).
- **CRM CSV**: `crm/crm_contacts.csv` (BOM, "NULL" strings, 2-digit years).

Every row carries lineage (`_source`, `_source_file`, `_source_row`, `_ingested_at`, `_raw_payload`). CDC stream and flaky-API examples from the brief are out of scope — called out below.

### Identity resolution (Challenge 4)

Two-pass:

1. **Deterministic merge** on strong keys: exact-match normalized email, normalized E.164 phone, source-provided FKs (`loyalty.pos_customer_id`).
2. **Fuzzy merge** within blocks `(last_initial, region, birth_year)` using `rapidfuzz` over `(normalized_name, street, city)`.

Survivorship is **field-level and explicit** in `pipeline/match.py`:

- `email`: prefer ecommerce > loyalty > crm > pos > acq_*.
- `phone`: prefer most-recent non-null, normalized to E.164.
- `birth_date`: prefer ecommerce/loyalty (user-entered) over POS.
- `full_name`: prefer the longest non-truncated value.
- Each field on the master row carries `<field>_source` and `<field>_confidence`.

Record-level confidence = floor of populated-field confidences. Thresholds: ≥0.90 auto-merge, 0.70–0.89 stewardship, <0.70 separate.

### Quality (Challenge 5)

Deterministic, in code, not in prompts:

- Schema drift vs. recorded contracts in `pipeline/schemas.py`. **BLOCK** the curated rebuild.
- Null explosion (per-column threshold). **ALERT.**
- Volume anomaly (row-count delta vs. baseline). **ALERT.**
- Referential integrity (`loyalty.pos_customer_id` ↔ `pos.cust_id`). **ALERT** — the cross-source FK is known-weak.

A `PreToolUse` hook (`.claude/hooks/curated_gate.sh`) blocks any `Write` into `warehouse/curated/` unless `quality.assert_contracts_pass()` returns clean.

## What we deliberately chose **not** to do

1. **No streaming.** CDC and flaky-API ingestion are stubs.
2. **No Iceberg/Delta.** DuckDB is the table format. We lose multi-writer ACID and time-travel beyond `_ingested_at`.
3. **No KMS-backed PII.** Hashes use a peppered salt baked into the repo (clearly labeled `DEMO_ONLY`).
4. **No stewardship UI persistence.** Review decisions live in `curated.customer_review` but a "save" only logs the decision; we don't re-run match in-place.
5. **No vendor MDM** (Reframa/Tamr/Informatica). The point of the hack is to show architecture and prompt/eval discipline.
6. **No probabilistic-record-linkage library (e.g. Splink).** We implement the matcher by hand so the eval harness measures *our* judgment.

## Consequences

- A new analyst can answer "how many customers do we have" in one query against `curated.customer_master`.
- A bad value in a curated row can be traced via `customer_xref` and `_raw_payload`. A CLI exists; an MCP server over the trace tools would be the Challenge-8 deliverable.
- The matcher is the part of the system most likely to be wrong, so it has the eval harness (Challenge 7) and a stratified golden dataset.
- The hooks-vs-prompts split is explicit: deterministic guardrails are hooks/code; preferences (zone semantics, naming) are prompts.

## References

- `CLAUDE.md` (root) — overall conventions.
- `warehouse/raw/CLAUDE.md`, `…/conformed/CLAUDE.md`, `…/curated/CLAUDE.md` — per-zone rules.
- `docs/the-mess.md` — Challenge 1 inventory of realistic issues already present in the source files.
- `backend/tests/golden_pairs.csv` — Challenge 7 evaluation set.
