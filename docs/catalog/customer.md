# Catalog — `curated.customer_master`

> **Audience:** business analysts, BI authors, anyone querying the gold
> layer. If you're a data engineer touching the conform or raw layers,
> read [`ADR-0001`](../../decisions/ADR-0001-blueprint.md) instead.

## What it is

One row per **resolved customer identity** at Fabrikam Retail. A
`customer_master` row is the system's best single answer to "who is this
person, across all our systems, as of the last pipeline run."

The table is rebuilt idempotently from `conformed.customer` on every
pipeline run. No row in `customer_master` is "original" — every value is
attributed to a source row in `customer_xref`.

## Where it comes from

Seven source systems contribute. Each has its own quirks, documented in
[`sources.md`](sources.md). The matcher decides which source rows are the
same person; survivorship then decides which value to keep per field.

| Source         | Contributes mostly | Trust for |
|----------------|--------------------|-----------|
| `ecommerce`    | email, modern address, birth_date | email (highest), name (user-entered) |
| `crm`          | phone, name, sales notes          | phone (when E.164-clean), name |
| `loyalty`      | tier, points, alt name spelling   | tier, loyalty_points |
| `pos`          | recent transactions, current address | last_seen, recency |
| `acq_northwind`| legacy ID, original DTADDED       | acquisition_date |
| `acq_rheinland`| German-market customers           | name (UTF-8 path), DE-formatted DOB |
| `acq_sunset`   | catalog-era customers             | mailing address (when not all-NULL) |

## How to trust it (record_confidence)

Each row has `record_confidence` in `[0, 1]`, computed as the floor of the
per-field confidences for the populated fields on the master row.

| Band      | What it means                                                           | Where the row lives                 |
|-----------|-------------------------------------------------------------------------|-------------------------------------|
| `>= 0.90` | Auto-merged. Strong-key match (email or phone) or a fuzzy match well above threshold. Safe for headline numbers. | `customer_master`                   |
| `0.70-0.89` | Plausible match, kept separate pending human review.                  | `customer_master` (still one row) + an entry in `customer_review` |
| `< 0.70`  | Not merged. Two distinct masters even if the names look close.          | Separate rows in `customer_master`. |

**Field-level**: each field on the master row also carries
`<field>_source` (which source contributed the surviving value) and
`<field>_confidence` (how strong that source's claim was). When an analyst
needs to know "where did this email come from," that's the answer.

## What "customer" means *here*

A `customer_master` row is **the resolved identity across the seven Fabrikam
source systems** — not a "customer of the e-commerce site" or "a member of
the loyalty program." It is the union with deduplication.

Implications:

- A row may exist with **no purchase history** (e.g. someone in CRM who
  never transacted).
- A row may exist with **no email** (e.g. a POS-only walk-in).
- `record_confidence < 1.0` does **not** mean the customer is fake — it
  means our matcher isn't certain this is one person rather than two.

## Caveats

- **PII is hashed.** `email_hash` and `phone_hash` are SHA-256 with a
  peppered salt; the salt is `DEMO_ONLY` in this hackathon repo. There
  is no way to recover the plaintext from `customer_master` alone — go
  to `conformed.customer` (DE/senior analysts) or `raw.<source>` (DEs).
- **Street is tokenized.** `street_tokens` is a set of normalized tokens
  (e.g. `{"5", "beacon", "st"}`), not a full address string.
- **Encoding-lossy rows are down-weighted.** Where a source row carried
  mojibake we couldn't recover (e.g. `Bj�rn Schonfeld` in
  `acq_sunset/SC1051`), the matcher discounts its contribution and the
  field carries `_encoding_lossy=True` upstream.
- **The cross-source FK `loyalty.pos_customer_id` is known-weak.** It
  raises an ALERT, not a BLOCK. Treat `loyalty <-> pos` links from this
  FK alone as a hint, not a proof.
- **Test/fake records are filtered upstream**, not represented here.
  (e.g. `MICKEY MOUSE`, `Vandelay, Art`, `TEST TEST DO NOT USE`.)
- **No GDPR erasure flow yet.** A right-to-be-forgotten request today
  has to be applied at the raw layer and re-run.

## Upstream contracts

The schema contract enforced by the pipeline lives in
[`backend/pipeline/schemas.py`](../../backend/pipeline/schemas.py). The
contract details — column names, types, nullability, PII policy — are
specified in [`ADR-0001 §3`](../../decisions/ADR-0001-blueprint.md#decision).

A schema drift in any source that breaks the contract **blocks** the
curated rebuild. The previous good `customer_master` snapshot remains
queryable until the contract is restored.
