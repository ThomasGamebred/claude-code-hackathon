# ADR-0002 — Three-level CLAUDE.md, survivorship & confidence

**Status:** Accepted · **Date:** 2026-06-30

## Three-level CLAUDE.md
- **Root** (`/CLAUDE.md`) — the overall pattern, conventions, the determinism split.
- **Per-zone** (`zones/{raw,conformed,curated}/CLAUDE.md`) — the rules that *differ*
  between zones: mutation policy, retention, PII, what may enter. Raw keeps everything;
  curated admits nothing without the contract. Putting these at the zone level means a
  contributor editing curated reads curated's rules, not a 300-line monolith.
- **User** (`~/.claude/CLAUDE.md`) — personal preferences, not in VCS.

## Survivorship rules (curated golden record)
When sources disagree on a field, the surviving value is chosen by, in order:
1. **Agreement** — the value the most source members share wins.
2. **Recency** — for volatile fields (address, phone, email), prefer the most recent
   `created_at`.
3. **Source trust** — `crm > ecommerce > loyalty > sunset > pos > rheinland > northwind`
   (customer-entered & well-cased beats uppercased/truncated legacy dumps).
4. **Completeness** — for names, the longest clean form (so "OBRIEN SEAN" loses to
   "Sean Patrick O'Brien").

Each field records **provenance** (which source won) and **confidence** (share of members
that agreed). The cluster's `match_confidence` is the **weakest connecting edge** — a
chain is only as trustworthy as its loosest link.

## What we deliberately chose NOT to do
- **No "golden source wins everything".** Per-field survivorship beats per-record: CRM may
  have the best name but a stale address. Field-level provenance captures that.
- **No averaging of confidences.** Min-of-edges is conservative on purpose; a transitive
  merge built from one weak link should *read* as weak.
