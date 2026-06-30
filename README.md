# Team SCV-Swampers

## Participants

- Kay Kartschewsky
- Thomas Schlütter
- Sebastian Loer
- Daniel Hartig
- Korbinian Kipp
- Julian Martin

## Scenario

**Scenario 3 — Data Engineering: Single Customer View.** Seven systems.
Zero agreement on what a customer is. Same person under four IDs, two
spellings, one mojibake'd umlaut. The CDO wants one trustworthy record.

We picked a three-zone lakehouse on DuckDB, a deterministic-plus-fuzzy
matcher with field-level survivorship, a React frontend that lets you
actually *see* the mess collapse into a golden record, an MCP server
exposing lineage tools to a fresh Claude session, and an eval harness in
CI that produces one defensible number for the CDO. All eight pursuable
challenges attempted, seven done, the ninth (The Swarm) deliberately
deferred.

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
| 8 | The Trace | done | Six-tool MCP server in [`mcp/`](mcp/) (`list_sources`, `preview_table`, `find_record`, `trace_lineage`, `get_source_schema`, `quality_status`) — descriptions written so a fresh Claude session picks the right tool first try. Lineage also rendered in the frontend. |
| 9 | The Swarm | skipped | Designed it on paper as per-source Task subagents emitting structured profile reports; deferred deliberately — eval depth on the matcher beats breadth on a ninth challenge. |

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

1. **Streaming ingestion.** Today every source is batch. Add a CDC stream
   shape (POS) and a flaky-API shape (loyalty) with backoff + retry budget.
2. **Stewardship UI persistence.** Review buttons log the decision but the
   matcher doesn't re-evaluate the cluster in-place. Wire it through.
3. **KMS-backed PII hashes.** The salt is currently `DEMO_ONLY` in the
   repo. Move it to an envelope-encrypted key.
4. **Address standardization.** We rely on rapidfuzz; USPS/CASS would lift
   recall on the boundary band.
5. **Multi-tenancy.** Today everything is global. Tenant-scoped tables and
   row-level filters in the API.
6. **The Swarm (Challenge 9).** Per-source profiling subagents that emit
   structured reports, aggregated into a "swamp health" dashboard.
7. **`fork_session` on the matcher.** Run two scoring schemes on the same
   golden set in parallel, compare false-confidence-rate, pick a winner.

## How We Used Claude Code

- **Parallel subagents with explicit context envelopes.** The scaffold
  landed in one coordinator turn that fanned out **four subagents at
  once**: one wrote the backend (pipeline + FastAPI + tests), one wrote
  the frontend (Vite/React/TS + mock-mode), one wrote the glue (Makefile,
  README, presentation, hooks, catalog), one wrote the MCP server.
  Each got the ADR, the relevant per-zone `CLAUDE.md`, and the API
  contract — no inherited coordinator context, no overlap. ~3 minutes,
  ~50 files.
- **Hooks for the curated-zone gate.** `.claude/hooks/curated_gate.sh`
  fires on `PreToolUse` for `Write` calls under `warehouse/curated/`. If
  `quality.assert_contracts_pass()` is red, the write is blocked. This is
  the cleanest split between deterministic guardrails (hooks) and
  probabilistic preferences (prompts) — the distinction the cert tests on.
- **Three-level CLAUDE.md.** Root at `CLAUDE.md` carries the project
  pattern. Per-zone files under `warehouse/<zone>/CLAUDE.md` carry what
  *differs* (mutation rule, PII policy, retention). When Claude is asked
  to write to a zone it reads the local file first.
- **MCP server with tool-design discipline.** `mcp/` exposes six tools
  with descriptions that include input formats, edge cases, and an
  explicit "Does NOT" clause per tool. Structured `reason_code` errors so
  the agent can recover gracefully. Six tools, not twelve — reliability
  drops past a handful.
- **Eval harness in CI.** `backend/tests/test_matcher_eval.py` runs on
  every PR against 24 stratified golden pairs (easy / hard / boundary /
  negative). Precision, recall, **false-confidence-rate** — one
  defensible number for the CDO when she asks "how good is this".
- **Validation-retry loop on parsing.** Strict format → dateutil fallback
  → reject row to `conformed._reject` with `reject_reason` and
  `reject_field`. Retry counts become evidence in the catalog.
- **Few-shot with a negative case.** `golden_pairs.csv` includes the
  matcher's hardest negatives by design: Sean Williams ≠ Sean Rodriguez,
  Jurgen Schmidt Berlin ≠ Jurgen Schmidt Köln. Two sharp boundary
  examples beat a paragraph of "be conservative".

## What We Tried to Break

A short list of adversarial moves the team made against its own pipeline,
because "best testing" isn't coverage:

- **The data already lies.** `pos/` has Mickey Mouse with $9,999,999
  lifetime spend and DOB in 2085. Vandelay & Art's `6/31/22` date. Test
  records on a blocklist, sanity bounds on DOB, spend-outlier check.
- **Encoding round-trips.** `acq_rheinland/` mixes UTF-8 and cp1252 *per
  row*. `acq_sunset/` and `pos/` have unrecoverable mojibake (`Bj�rn`,
  `D�ANGELO`). Ingest flags `_encoding_lossy=True`; the matcher
  down-weights name when set.
- **Schema drift.** A schema-drift check (BLOCK) compares raw column lists
  to recorded contracts before curated rebuilds. We hand-broke the contract
  to confirm the curated zone refuses to advance.
- **Same name, different person.** The negative golden pairs ensure the
  matcher doesn't over-merge on first-name + city alone.

---

`presentation.html` lives at the repo root.
