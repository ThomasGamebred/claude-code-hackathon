# The Swarm — parallel source profiling (Challenge 9)

Goal: a "swamp health" dashboard built by profiling each source **in parallel**, one
subagent per source, then aggregating. The decomposition must be **legible** — so this
doc shows exactly what each subagent receives, because subagents do **not** inherit the
coordinator's context (it's passed explicitly in each Task prompt).

## Two execution modes (same scoring)

- **Deterministic coordinator** — `make profile` / `python -m pipeline.profile`. Runs
  `profile_source()` for all seven sources and aggregates to `build/swamp_health.json`.
  Reproducible, offline, CI-friendly. This is the version that ships.
- **Agentic swarm** — a Claude coordinator dispatches one `Task` subagent per source. Each
  gets only the prompt below (no shared memory), reads `raw_customer` for its source, and
  returns the SAME structured report. The coordinator aggregates identically.

## The exact context each subagent receives

The template is `pipeline.profile.SUBAGENT_PROMPT`. Rendered for one source, a subagent's
*entire* context is:

```
You are profiling ONE source system in the Fabrikam Customer-360 swamp. Context you need
(you do NOT inherit anything else):

  source        = loyalty
  raw table     = raw_customer (filter source_system = 'loyalty')
  contract      = {key: 'member_id', columns: [...], tz: 'America/Chicago',
                   notes: 'enrolled_at is naive store-local time ...'}
  warehouse     = warehouse.duckdb (DuckDB, read-only)

Score these 0..1 (1 = healthy) and return STRICT JSON with keys
{completeness, freshness, key_coverage, anomaly_count, pii_surface, notes}:
  - completeness : share of non-empty values across the contract's identity fields
  - freshness    : how recent the newest record is (decay over 24 months)
  - key_coverage : share of rows with a usable natural key
  - anomaly_count: integer count of obviously bad rows (sentinels, empty, � encoding)
  - pii_surface  : how many PII field types are present unmasked
  - notes        : one sentence an analyst would care about
Do not invent rows. Read only raw_customer for your source.
```

Seven of these run concurrently — `pos`, `ecommerce`, `loyalty`, `crm`, `acq_rheinland`,
`acq_sunset`, `acq_northwind` — each blind to the others. The coordinator collects the
seven JSON reports and computes the swamp health (mean), worst source, and totals.

## Why explicit context, not inheritance
A subagent that "just knows" the coordinator's state is a subagent you can't reason about
or replay. Passing the source, its contract, and the rubric in the prompt makes each unit
of work a pure function of its input — which is exactly what makes the swarm legible to a
reviewer and deterministic to re-run. (Same principle the cert stresses for Task agents.)

## Result (latest run)
Swamp health **0.81** across 247 rows, 4 anomalies. Worst source by health: loyalty
(naive-timezone enrolment + a NULL home_store). See `build/swamp_health.json`.
