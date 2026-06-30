# Team Swamp Drainers

> Seven systems. Zero agreement on what a "customer" is. One trustworthy record out the other end.

## Participants
- Julian Martin (PM · Architect · Data Engineer · Tester — played every role)
- Claude Opus 4.8 (pair engineer, via Claude Code)

## Scenario
**Scenario 3: Data Engineering — "The Swamp."** Fabrikam Retail has seven source systems
(POS, e-commerce, loyalty, CRM, and three acquisitions). Same person, four IDs, two
spellings. The new CDO wants a single source of truth.

## What We Built
A **runnable lakehouse** that ingests all seven sources, conforms them to one schema,
resolves duplicate humans into **golden customer records with confidence scores**, and
guards the whole thing with deterministic data-quality checks — all on **DuckDB + the
Python stdlib**, no cloud, no Spark. `make setup && make build && make eval` reproduces
everything from the raw files in under a minute.

What exists now that didn't before:
- A medallion pipeline (`raw → conformed → curated`) with **end-to-end lineage** — any
  value in a golden record walks back to the exact source row it came from.
- A **parse-validate-retry** intake loop that turns 247 messy rows into 246 conformed
  rows (1 quarantined), logging *why* each of the 33 retried rows needed repair.
- An **explainable entity matcher** (blocking → scored pairs → survivorship) producing
  **227 golden records** from 246 rows, with per-field provenance + confidence and a
  human review queue for the genuinely-uncertain.
- A **matcher eval** (precision / recall / **false-confidence rate**, stratified) that
  **runs in CI and gates merges** — and which drove three real matcher fixes during the build.
- A **`PreToolUse` hook** that blocks any write to the curated zone while its schema
  contract is failing, plus a **lineage MCP server** and a **parallel profiling swarm**.

What's faked / scaffolding: the entity *matcher* is deterministic rather than an LLM call
(so the eval is reproducible offline) — the few-shot prompt it implements is in
`pipeline/matcher_prompt.md` and the swap is one function. The "CDC stream" and "flaky
API" intake shapes are modelled over static files.

## Challenges Attempted
| # | Challenge | Status | Notes |
|---|---|---|---|
| 1 | The Mess | done (inspect) | Defects catalogued in `docs/the_mess.md`; the provided data is genuinely nasty (mojibake twins, Excel-serial dates, templated emails, a timezone bug). |
| 2 | The Blueprint | done | Lakehouse ADRs incl. "what we chose **not** to do"; three-level `CLAUDE.md`. |
| 3 | The Intake | done | All 7 sources → raw with lineage; parse-validate-retry loop with per-row `retry_count` + `error_type`. |
| 4 | The Customer | done | Survivorship + golden record with field-level confidence; boundary-first few-shot incl. a negative case. |
| 5 | The Tripwire | done | DQ checks tagged break-vs-alert; `PreToolUse` hook blocks curated writes until the contract passes. |
| 6 | The Catalog | done | Analyst-facing entries in `catalog/`, each linked to its producer contract. |
| 7 | The Scorecard | done | Golden labelled pairs; precision/recall/false-confidence, stratified; **gates CI**. |
| 8 | The Trace | done | MCP server: `preview_table`, `trace_lineage`, `find_record`, `get_source_schema` with structured errors. |
| 9 | The Swarm | done | Parallel per-source profiling → swamp-health dashboard; explicit per-subagent context in `docs/swarm.md`. |

## Key Decisions
The big one: **deterministic guardrails in code, probabilistic judgement isolated and
eval-gated.** DQ checks and the curated contract are exact, so they're code + a hook.
Entity matching is fuzzy, so it's one scored function behind a scorecard. We never put a
guardrail in a prompt or a fuzzy call in a hook. Full reasoning in `decisions/`:
- [ADR-0001](decisions/0001-lakehouse-on-duckdb.md) — lakehouse on DuckDB (+ what we skipped: Spark, mesh, streaming, ML).
- [ADR-0002](decisions/0002-three-level-claude-md-and-survivorship.md) — three-level `CLAUDE.md`, survivorship, confidence.
- [ADR-0005](decisions/0005-guardrails-in-code-preferences-in-prompts.md) — hooks vs prompts: the determinism split.

## How to Run It
Assumes `python3`. No Docker needed (DuckDB is embedded).
```bash
make setup     # create venv, install duckdb (+ pytz)
make build     # raw → conformed → [DQ gate] → curated golden records
make eval      # score the matcher against the golden set (the CI gate)
make profile   # parallel source profiling → swamp-health dashboard
make dq        # data-quality report
make test      # unit tests for normalizers + matcher
```
Then poke the warehouse: `.venv/bin/python -c "import duckdb; print(duckdb.connect('warehouse.duckdb').sql('SELECT full_name, member_sources, match_confidence FROM curated_customer WHERE member_count>1'))"`

## If We Had More Time
1. **Swap the matcher to a real LLM call** for the `[0.72, 0.90)` review band only —
   deterministic rules decide the easy 90%, Claude adjudicates the hard 10% (the prompt
   already exists). Keep the eval as the gate.
2. **Incremental / CDC ingestion** instead of full rebuilds; the lineage model already supports it.
3. **Resolve the 10 dangling `loyalty → POS` FKs** the Tripwire flags (currently an alert).
4. **Grow the golden set to ~200 pairs** with active learning from the review queue, and
   add calibration so `match_confidence` is a true probability.
5. Persist zones as Parquet on object storage to make the "lakehouse" literal.

## How We Used Claude Code
- **The eval caught Claude's own bugs.** Three matcher flaws (reordered-name miss,
  templated-email false-positive, German-phone-format miss) were found by `make eval`
  failing, not by us reading code. The harness, not the human, drove the fixes.
- **Hooks made guardrails real.** The `PreToolUse` curated guard turned "please don't
  corrupt curated" from a hope into an enforced invariant we could demo (block → fix → allow).
- **Three-level `CLAUDE.md`** kept the agent honest about zone rules — it stopped trying
  to "just clean one field" in the raw zone once the raw-zone `CLAUDE.md` said not to.
- **Commit-as-we-go** — the history is the journey: scaffold → intake → matcher → eval-driven fixes → blueprint.
- Biggest surprise: how much leverage came from *separating determinism from judgement*
  up front. Once that line was drawn, every later decision had an obvious home.
