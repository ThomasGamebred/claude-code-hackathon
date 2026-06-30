# CLAUDE.md — Fabrikam Customer-360 (repo root)

This repo turns **seven disagreeing source systems** into **one trustworthy customer
record**. It's a lakehouse you can run on a laptop: DuckDB + the Python stdlib, no cloud.

> **Three-level `CLAUDE.md`.** This root file holds the overall pattern. Each zone
> (`zones/raw`, `zones/conformed`, `zones/curated`) has its own `CLAUDE.md` with the
> rules that differ there (mutation, retention, PII). Personal preferences live at the
> user level (`~/.claude/CLAUDE.md`), not here. See ADR-0002.

## The shape

```
7 sources ──ingest──▶ RAW ──conform──▶ CONFORMED ──[DQ gate]──resolve──▶ CURATED
 pos, ecommerce,      verbatim         one canonical    Tripwire        golden records
 loyalty, crm,        + lineage        schema, cleaned  blocks bad      (1 row / person)
 3 acquisitions                        (retry loop)     writes
```

- `pipeline/` — the engine. `ingest` → `conform` → `dq` → `resolve`.
- `scripts/run_pipeline.py` — one command builds the whole warehouse.
- `eval/` — the matcher scorecard, runs in CI.
- `mcp/` — lineage MCP server (preview / trace / find / schema).
- `hooks/` — `PreToolUse` guard on the curated zone.
- `catalog/` — analyst-facing entries for each entity.
- `decisions/` — ADRs (read these first to understand *why*).

## How to work in this repo

- **Run it:** `make setup && make build && make eval`. Everything is reproducible
  from the source files; `warehouse.duckdb` is a build artifact, never committed.
- **Determinism vs. judgement.** Deterministic rules (normalizers, DQ checks, the
  curated contract) live in **code** and are unit-tested. Probabilistic judgement
  (entity matching) is **isolated** in `resolve.score_pair` and is **eval-gated** —
  never tune it without re-running `make eval`. This split is the spine of the design
  (ADR-0005). Respect it: don't move a guardrail into a prompt, or a fuzzy call into a hook.
- **Lineage is sacred.** Every row from raw onward carries a `lineage_id`. Any value in
  curated can be walked back to its source row. Don't add a transform that drops it.
- **The matcher has one source of truth for its rules:** `pipeline/matcher_prompt.md`
  (few-shot, boundary-first). `resolve.score_pair` implements those same rules. If you
  change one, change both and add a golden pair to `eval/golden_pairs.csv`.

## Conventions

- Python 3, stdlib + `duckdb` only. No pandas/Spark. Keep the dependency list tiny.
- Normalizers return `""`/`None` for "absent", never raise on bad input — raw takes
  everything; cleaning happens in `conform`, never in `ingest`.
- Money/dates/phones/names: always go through `pipeline/common.py`. Do not re-parse
  inline — the seven sources have seven format conventions and they're all handled there.
- Commit small and often; the commit history is part of the story.

## What "customer" means here

A **golden record** in `curated_customer` = one physical person, assembled from 1+ source
rows by survivorship rules, carrying a `match_confidence` (weakest link in its merge
chain) and **per-field** provenance + confidence. "Customer" is defined in
`catalog/customer.md` for analysts; the producer contracts are in `pipeline/contracts.py`.
