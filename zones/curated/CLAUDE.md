# CLAUDE.md — CURATED zone

**Rule of the zone: this is what analysts trust. Nothing enters without passing the contract.**

- **Mutation:** rebuilt from conformed by `resolve.py`. One row per *physical person*
  (golden record), assembled by survivorship rules with **field-level** provenance +
  confidence and a cluster `match_confidence` (weakest connecting edge).
- **The contract is enforced, not suggested.** `CURATED_CONTRACT` in
  `pipeline/contracts.py` defines required columns, non-null fields, ranges, uniqueness.
  Two things enforce it:
    1. `scripts/run_pipeline.py` runs the DQ gate before/after the curated write.
    2. `hooks/curated_guard.py` (`PreToolUse`) **blocks** any manual `Write`/`Edit`/SQL
       write touching the curated zone until the contract passes. This is a deterministic
       guardrail (ADR-0005) — it is not optional and not a prompt.
- **Confidence is first-class.** Every golden field has a confidence = share of source
  members that agreed. Surface it to analysts; never present a survived value as fact
  without it. The matcher itself is eval-gated (`make eval`) — don't tune thresholds
  without re-running the scorecard.
- **Retention:** curated is rebuildable from raw, so it's disposable. Raw is the SoR.
- **PII:** curated is the read surface for analytics. Apply least-privilege at read time;
  `PostToolUse` redaction is the place to mask PII heading into logs/exports (ADR-0005).

If a golden record looks wrong, **don't patch curated** — fix the rule in `resolve.py`
or `conform.py`, add a golden pair, and rebuild. Curated has no hand edits.
