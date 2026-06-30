# The Mess — defect inventory (Challenge 1, inspection half)

We used the provided source data (it's genuinely realistic "good bad data", not synthetic
noise). This is the catalogue of what's wrong with it and where each defect is handled.

| # | Defect | Where it lives | Example | Handled by |
|---|---|---|---|---|
| 1 | **Same person, many IDs** | all sources | Maria Hernandez in pos/ecom/loyalty/crm/sunset | entity resolution → 1 golden record |
| 2 | **Mojibake (UTF-8 as Latin-1)** | acq_rheinland | `JÃ¼rgen MÃ¼ller` for `Jürgen Müller` | `common.repair_mojibake` + retry loop |
| 3 | **Lossy encoding (U+FFFD)** | acq_sunset, pos | `Bj�rn`, `MU�OZ, JOS�` | `has_lossy_encoding` flag (unrecoverable, surfaced) |
| 4 | **Mojibake duplicate rows** | acq_rheinland | RH-1001 clean vs RH-1188 corrupted twin | matched + merged (golden) |
| 5 | **Excel serial dates** | acq_sunset | `44197` = 2021-01-01 | `common.parse_date` serial branch |
| 6 | **Mixed date formats** | everywhere | `19851201`, `02.09.1975`, `7/22/85`, `03/15/2021` | format zoo in `parse_date` (+ dayfirst retry) |
| 7 | **German number format** | acq_rheinland | `12.840,55` (= 12840.55) | `common.parse_money` |
| 8 | **Timezone bug** | loyalty | `enrolled_at` is naive store-local time | shifted to UTC on conform (`assume_tz`) |
| 9 | **Phone format chaos** | all | `+1-973-555-0142`, `(973) 555-0142`, `973.555.0142`, `…x4` | `common.normalize_phone` (+ extension strip) |
| 10 | **Zip leading-zero loss** | pos | `7102` should be `07102` | `common.normalize_zip` (zfill) |
| 11 | **Name order / punctuation** | pos, crm | `HERNANDEZ, MARIA J` vs `Maria Hernandez` | token-sorted `normalize_name` + matcher containment |
| 12 | **Truncated names** | acq_northwind | `HALPERT JAMES MICHAE` (cut at ~20) | tolerated by fuzzy name match |
| 13 | **Templated emails** | acq_sunset | two people share `firstname.lastname@…` | matcher downgrades shared-email-with-conflict |
| 14 | **Literal "NULL" strings** | crm | `"NULL"` text in phone/email | treated as absent in normalizers |
| 15 | **Junk / test rows** | pos, crm | `TEST TEST DO NOT USE`, `Ghost Holdings LLC` | anomaly count; empty-identity quarantine |
| 16 | **Embedded newlines in CSV** | acq_sunset | multiline quoted address/notes | `csv` reader handles quoted newlines |
| 17 | **Ragged rows / extra commas** | acq_sunset | address with unquoted comma | DictReader `restkey="_overflow"` |
| 18 | **Duplicate register profiles** | pos | CUST_ID 100231 appears twice | collapsed in resolution |
| 19 | **Dangling foreign keys** | loyalty→pos | `pos_customer_id` not in POS | Tripwire referential-integrity alert (10 found) |
| 20 | **Sentinel values** | all | `999999`, `00000000`, `01/01/1900`, `000-000-0000` | sentinel lists in normalizers |

**Evidence the handling is real:** `make build` reports 77 rows hitting the retry loop
(BAD_DATE ×16, BAD_EMAIL ×11, BAD_ENCODING ×3), 1 quarantined; `make dq` flags the 10
dangling FKs; `make profile` counts anomalies per source.
