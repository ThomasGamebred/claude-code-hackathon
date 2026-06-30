# CLAUDE.md — CONFORMED zone

**Rule of the zone: one canonical schema, one row per source row. Clean, don't merge.**

- **Mutation:** transform-on-write. Every source maps onto `CONFORMED_SCHEMA`
  (`pipeline/contracts.py`). Rows stay 1:1 with raw — no entity resolution here, that's
  curated's job. Each row keeps its `lineage_id` back to raw.
- **The retry loop is the law of this zone.** Parsing goes parse → validate → feed the
  specific error back → targeted repair → retry (max 3). Log `retry_count` + `error_type`
  per row to `conform_log`. Don't add a parser that fails silently; route failures
  through the loop so they show up as evidence.
- **Quarantine, don't drop.** A row with no identity anchor (no name, email, or phone)
  is quarantined (logged, not written), never silently discarded.
- **Standardization lives in `common.py`.** Names, emails, phones, money, dates, zips,
  encoding repair. If two sources disagree on a format, the reconciliation goes there,
  with a comment naming the sources.
- **Retention / PII:** still unmasked PII. Same handling as raw. The `attributes` JSON
  column carries source-specific extras (tier, spend, opt-in) — keep it, analysts use it.

When you add a source, add its contract + a `_map()` branch in `conform.py`. Don't
special-case it anywhere else.
