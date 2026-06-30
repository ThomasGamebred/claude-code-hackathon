# ADR-0001 — Lakehouse on DuckDB, medallion zones

**Status:** Accepted · **Date:** 2026-06-30

## Context
Seven source systems, no agreement on "customer". The CDO wants a single source of
truth. A hackathon needs something a judge can `git clone` and run in two minutes.

## Decision
A **lakehouse** with **medallion zones** (raw → conformed → curated), all in a single
**DuckDB** file.

- **Raw** — verbatim source bytes + lineage. Immutable. System of record.
- **Conformed** — one canonical schema, 1:1 with raw, cleaned via a validation-retry loop.
- **Curated** — golden records (one per person) behind an enforced contract.

DuckDB because it gives warehouse SQL semantics with zero infrastructure: one file, no
server, reads CSV/JSON natively, runs in CI. The zone *pattern* is portable — the same
DDL and contracts map onto Snowflake/BigQuery + object storage unchanged.

## What we deliberately chose NOT to do
- **No Spark / cloud warehouse.** Right for petabytes; wrong for a laptop demo and a
  reviewer's two minutes. The architecture transfers; the bill doesn't.
- **No data mesh.** Mesh distributes ownership across domain teams. Fabrikam's problem
  is the *opposite* — no one owns the customer entity yet. Centralize first, federate later.
- **No streaming-first / Kafka.** One source is "CDC-like"; we model it row-by-row in the
  intake. Real CDC is a swap of the `ingest` reader, not a re-architecture.
- **No ML matching model (yet).** A deterministic, explainable, eval-gated matcher beats
  an opaque model for a trust project where the CDO must defend every merge. ML is a
  later upgrade behind the same eval.
