# Conformed zone

**Rule:** canonical schema, idempotent rebuild from raw, normalized but unhashed.

- **One table for all customer-shaped records**: `conformed.customer`. Source-specific columns are dropped; everything maps to the canonical schema in `pipeline/schemas.py::CONFORMED_DDL`.
- **Rejects go to `conformed._reject`** with `reject_reason` and `reject_field`. Never silently coerce; never drop.
- **Validation-retry on parsing**: try strict format → dateutil fallback → reject. Log the retry path in `field_quality_flags`.
- **PII**: normalized (E.164 phones, lowercased emails, NFKC names) but **not** hashed. Hashing happens in curated.
- **Mutation**: idempotent rebuild. `DELETE FROM conformed.customer` then INSERT — no UPDATEs.
- **Retention**: 7 years.
- **Who reads it**: DEs and senior analysts only. Analyst-facing dashboards read curated.

If you write a transformation here, ask yourself: is this a *normalization* (same fact, cleaner form), or is this a *business decision* (which of two facts wins)? Business decisions belong in `match.py` / curated.
