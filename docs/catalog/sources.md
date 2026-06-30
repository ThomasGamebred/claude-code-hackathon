# Catalog — Source Systems

Seven source systems feed `curated.customer_master`. Each one lands
verbatim in `raw.<source>` with full lineage columns, then is reshaped
into the canonical schema in `conformed.customer`.

This page is the one-stop summary for analysts. For the deep inspection
of every known data issue, read [`docs/the-mess.md`](../the-mess.md).

## Summary

| # | Source            | File                                           | Rows | Primary key      | Freshness        | Ingest | Trust   | Known-issues link |
|---|-------------------|------------------------------------------------|------|------------------|------------------|--------|---------|-------------------|
| 1 | `acq_northwind`   | `acq_northwind/legacy_customers.txt`           | 34   | `CUST_ID`        | static (acq feed)| batch  | medium  | [the-mess §northwind](../the-mess.md#acq_northwindlegacy_customerstxt--34-rows-pipe-delimited) |
| 2 | `acq_rheinland`   | `acq_rheinland/kunden.csv`                     | 30   | `KundenNr`       | static (acq feed)| batch  | medium  | [the-mess §rheinland](../the-mess.md#acq_rheinlandkundencsv--30-rows-semicolon-delimited) |
| 3 | `acq_sunset`      | `acq_sunset/catalog_customers.csv`             | 30   | `customer_code`  | static (acq feed)| batch  | low     | [the-mess §sunset](../the-mess.md#acq_sunsetcatalog_customerscsv--30-rows) |
| 4 | `crm`             | `crm/crm_contacts.csv`                         | 31   | `contact_id`     | daily export     | batch  | medium  | [the-mess §crm](../the-mess.md#crmcrm_contactscsv--31-rows) |
| 5 | `ecommerce`       | `ecommerce/customers.json`                     | ~30  | `customer_id`    | daily export     | batch  | high    | [the-mess §ecommerce](../the-mess.md#ecommercecustomersjson--30-customers-nested) |
| 6 | `loyalty`         | `loyalty/loyalty_members.csv`                  | 37   | `member_id`      | daily export     | batch  | medium  | [the-mess §loyalty](../the-mess.md#loyaltyloyalty_memberscsv--37-rows) |
| 7 | `pos`             | `pos/pos_export_2023-11.csv`                   | 49   | `cust_id`        | monthly export   | batch  | medium  | [the-mess §pos](../the-mess.md#pospos_export_2023-11csv--49-rows) |

Row counts reflect the seed snapshot in the repo; they will change once
real exports arrive.

## Trust levels — what they mean

- **high**: schema is stable, encoding is clean, the source enforces email
  uniqueness or similar invariants. Safe to treat fields from this source
  as authoritative on a tie.
- **medium**: the source is well-defined but has known quirks (mixed
  date formats, mojibake, sentinel values). Conform-layer cleanup catches
  most of it; the matcher down-weights the rest.
- **low**: the source has structural problems (column misalignment,
  encoding losses we can't recover). The matcher uses these rows but
  rarely as the surviving value for a field.

## Ingest mode

All sources are **batch** today. The pipeline is idempotent — re-running
`make pipeline` produces the same warehouse state. CDC streams and
flaky-API ingestion are scoped out (see ADR-0001).

## Per-field provenance

When you look at `customer_master`, every populated field carries
`<field>_source` pointing back to one of these seven. The lineage chain
`curated.customer_master -> customer_xref -> conformed.customer -> raw.<source>`
is queryable end-to-end; see the **Lineage** page in the frontend, or
`GET /api/customers/{id}/lineage`.

## See also

- [`docs/catalog/customer.md`](customer.md) — what `customer_master`
  means and how to trust the confidence score.
- [`decisions/ADR-0001-blueprint.md`](../../decisions/ADR-0001-blueprint.md)
  — full architecture, zone rules, PII policy.
- [`docs/the-mess.md`](../the-mess.md) — Challenge 1 inspection notes,
  cross-source matcher cases.
