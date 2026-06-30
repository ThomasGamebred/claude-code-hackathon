# Curated zone

**Rule:** golden record, idempotent rebuild from conformed, PII hashed/tokenized.

- **`customer_master`** is the single source of truth. One row per resolved identity. Each field carries `<field>_source` and `<field>_confidence`.
- **`customer_xref`** maps every source row that contributed to a master. This is the entry point for the lineage trace.
- **`customer_review`** holds pairs that scored in the 0.70–0.89 band — the stewardship queue.
- **`match_audit`** records the decision for every cluster (merge / singleton / split).
- **PII**: emails and phones SHA-256 with a peppered salt (see `normalize._PII_PEPPER`, demo-only). Street is tokenized to a 16-char prefix of its hash.
- **Mutation**: idempotent rebuild. Never UPDATE a master row in place — re-run match.
- **Retention**: 7 years.
- **Who reads it**: analysts, BI, downstream apps.

A `PreToolUse` hook (`.claude/hooks/curated_gate.sh`) blocks any write into this zone unless `quality.assert_contracts_pass()` is green. If you need to write here from Claude, fix the quality failures first; do not disable the hook.
