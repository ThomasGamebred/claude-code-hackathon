# Catalog: `customer` (the golden record)

*Written for an analyst, not an engineer.*

## What is this?
One row per **real human being**, assembled from up to seven source systems. If Maria
Hernandez shopped in-store, online, joined the loyalty program, and showed up in two
acquired databases, she is **one row here** — not five. Table: `curated_customer`.

## Can I trust it?
Mostly — and the row tells you how much. Two trust signals travel with every record:

- **`match_confidence`** (0–1): how sure we are this is genuinely one person. It's the
  *weakest link* in the merge: a record built only from rock-solid matches scores ~0.98;
  one that leaned on a single fuzzy link scores lower. **Filter on this** for high-stakes work.
- **`field_confidence`** (JSON, per field): for each value (name, email, address…), the
  share of source systems that agreed on it. A `phone` at confidence `1.0` means every
  source agreed; `0.5` means they were split and we picked one.

`field_provenance` (JSON) tells you *which* source each surviving value came from. So you
can answer "whose address is this?" → e.g. `{"street": "crm", "phone": "ecommerce"}`.

Records we **weren't** sure about did **not** get merged blindly — they're in
`match_review_queue` for a human. Nothing uncertain was silently fused into a golden record.

## What does "customer" mean *here*?
A resolved identity, **not** an account, not a transaction. One person with many accounts
is still one customer. Survivorship (which value wins on conflict) is defined in
[ADR-0002](../decisions/0002-three-level-claude-md-and-survivorship.md): agreement →
recency → source trust → completeness.

## Where did it come from?
Seven sources → conformed to one schema → entity-resolved. Each golden record carries
`member_lineage_ids` and `member_sources`. Walk any value back to its origin row with the
`trace_lineage` MCP tool (Challenge 8) or:
```sql
SELECT member_sources, match_confidence, field_confidence
FROM curated_customer WHERE golden_id = 'G-...';
```

## Upstream contracts
This entity is built from these producers — see each promise in
[`pipeline/contracts.py`](../pipeline/contracts.py):

| Source | Contract key | Trust | Known quirk |
|---|---|---|---|
| CRM | `crm` | highest | BOM, literal "NULL" strings, junk accounts |
| E-commerce | `ecommerce` | high | nested address, ISO-8601 UTC timestamps |
| Loyalty | `loyalty` | high | **naive store-local timestamps** (timezone bug), FK to POS |
| Sunset (acq.) | `acq_sunset` | med | Excel-serial dates, templated emails, embedded newlines |
| POS | `pos` | med | "LAST, FIRST" names, zip loses leading 0, duplicate register profiles |
| Rheinland (acq.) | `acq_rheinland` | low | German formats; mojibake duplicate rows |
| Northwind (acq.) | `acq_northwind` | low | legacy AS/400 dump, names truncated ~20 chars |

## Caveats an analyst should know
- ~227 golden records from 246 conformed rows; 13 borderline pairs are awaiting review.
- The loyalty timezone bug is **fixed on ingest** (shifted to UTC) — but historical
  exports you have lying around are not. Use this table, not the CSVs.
- 10 loyalty records point at POS customer IDs that don't exist (dangling FK) — flagged
  by the Tripwire as an alert, not yet resolved.
