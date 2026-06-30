# The Mess — Inventory of Realistic Data Issues

Challenge 1 has two halves: *generate* good bad data, and *inspect* what's there. The source files in this repo already contain a thick layer of realistic mess; this document is the inspection half.

Every issue here maps to either (a) a conform-layer transformation, (b) a quality check, or (c) a matcher decision. Issues we noted but **don't** handle are listed at the bottom.

## Source-by-source inventory

### `acq_northwind/legacy_customers.txt`  (34 rows, pipe-delimited)

| Issue | Example | Where it's handled |
|---|---|---|
| Names truncated mid-character | `HALPERT JAMES MICHAE` | Matcher: prefer longer name from another source. |
| Sentinel for missing DOB | `00000000` | `normalize.parse_date` → NULL. |
| Single name field, ambiguous order | `WIERZBICKI-KOWALCZYK` | Tokenize on space; first token = last name when ALL CAPS + known-surname. |
| Status codes opaque (`A`/`I`/`D`) | column STATUS | Not currently mapped — could enrich downstream. |
| 8-digit dates without separators | DTADDED `19850114` | `parse_date(formats=("%Y%m%d",))`. |

### `acq_rheinland/kunden.csv`  (30 rows, semicolon-delimited)

| Issue | Example | Where it's handled |
|---|---|---|
| **Mixed encodings.** Some rows UTF-8, some cp1252 misread | row 2 vs row 3 (`JÃ¼rgen MÃ¼ller`) | `ingest.ingest_rheinland`: per-row heuristic — if mojibake markers present, re-decode as cp1252, flag `_encoding_fixed=True`. |
| German date format `dd.mm.yyyy` | `02.09.1975` | `parse_date(formats=("%d.%m.%Y",))`. |
| Euro decimals `12.840,55` | column Umsatz | `normalize.parse_de_decimal`. |
| Newsletter as Ja/Nein | column Newsletter | Conform layer maps to boolean. |
| **Same person, two IDs.** `RH-1001` is `Jürgen Müller`, `RH-1188` is the mojibake'd duplicate with shortened email | matcher gold-pair | Matcher headline case — encoding-robust string matching. |
| Surname-comma-firstname mixed with firstname-surname | `Greß, Greta` vs `Mia Wagner` | `split_full_name` handles both. |

### `acq_sunset/catalog_customers.csv`  (30 rows)

| Issue | Example | Where it's handled |
|---|---|---|
| **Excel-serial dates** alongside string dates | `44197` (= 2021-01-01) vs `03/15/2021` | `parse_date` detects 5-digit ints, converts via Excel epoch (1899-12-30). |
| Embedded newlines inside quoted field | SC1040 address spans two lines | Standard CSV reader. |
| Comma inside unquoted address field | SC1033 `500 Oak Ave, Suite 4` | Conform layer rejects on column-count mismatch. |
| Smart quotes (`Tony D'Angelo`) | SC1021 | NFKC normalize. |
| Mojibake from prior round-trip (`Bj�rn Schonfeld`) | SC1051 | Cannot recover; verbatim, `_encoding_lossy=True`. |
| **All-NULL row** | SC1099 | Quality: null-explosion → reject. |
| **Phone field contains a date** (column misalignment) | SC1021 `03/15/2021` | `normalize_phone` returns None → flagged. |

### `crm/crm_contacts.csv`  (31 rows)

| Issue | Example | Where it's handled |
|---|---|---|
| **BOM** at start of file | row 1 | `ingest.ingest_crm`: `utf-8-sig`. |
| `"NULL"` as literal string | many rows | Conform layer replaces with NULL. |
| **2-digit years** in DOB/created | `7/22/85`, `3/2/21` | `parse_date(formats=("%m/%d/%y", "%m/%d/%Y"))`; pivot at 30. |
| **Impossible date** | `6/31/22` (Vandelay) | Reject with reason `invalid_date`. |
| Test/fake records | `Vandelay, Art` | `_is_test_record` blocklist → reject. |
| Phone formats mixed | `(973) 555-0142`, `6175550211`, `NULL` | `phonenumbers` lib, default US. |

### `ecommerce/customers.json`  (≈30 customers, nested)

| Issue | Example | Where it's handled |
|---|---|---|
| Nested address object | `shipping_address.line1` | `ingest.ingest_ecommerce`: flatten. |
| **Same person, three accounts** (David / Dave / D Lee) | `ec_9001`, `ec_9002`, `ec_9003` | **Headline matcher test.** All three in `golden_pairs.csv`. ec_9003 has `+amazon` alias → boundary case. |
| ISO timestamps with `Z` | `2021-06-02T14:11:09Z` | `parse_date` via dateutil. |
| Case-inconsistent city/region | `seattle`/`wa` | Conform: uppercase region. |

### `loyalty/loyalty_members.csv`  (37 rows)

| Issue | Example | Where it's handled |
|---|---|---|
| **Cross-source FK** `pos_customer_id` with sentinels | `999999`, `NULL`, blank | Quality: referential integrity. Sentinel rejected. |
| Tier capitalization inconsistent | `Gold`, `gold`, `GOLD`, blank | Conform: upper enum. |
| Thousands separator in numeric | `"12,500"` | Strip comma. |
| **Negative points** sentinel | `-50` everywhere | Conform clamps to NULL. |
| **`0000-00-00` zero-date** | LY-50103 et al | Conform: NULL. |
| **Same person under different name variants** | `María J. García` vs CRM `Hernandez-Garcia, Maria Jose` vs POS `HERNANDEZ GARCIA, MARIA J` | Matcher headline; phone exact match wins. |

### `pos/pos_export_2023-11.csv`  (49 rows)

| Issue | Example | Where it's handled |
|---|---|---|
| **Leading-zero ZIP truncation** | `7102` (was `07102`) | `normalize.pad_us_zip`. |
| **Within-source duplicates** | `100231` Smith Robert twice, slightly different addresses | Survivorship: longest non-truncated; recency tiebreak; conflict logged in `match_audit`. |
| `N/A` string sentinel | DOB, EMAIL | Conform: NULL. |
| **Mojibake** | `D�ANGELO`, `MU�OZ` | `_encoding_lossy=True`. |
| **Test/fake rows** | `MICKEY MOUSE` DOB 2085 spend 9999999, `TEST TEST DO NOT USE` | Blocklist + DOB-sanity + spend-outlier → reject. |
| Phone with extension | `(312) 555-0188 x4` | `phonenumbers` strips ext into `_phone_ext`. |
| MM/DD/YYYY date format | DOB, LAST_TXN_DATE | `parse_date(formats=("%m/%d/%Y",))`. |

## Cross-source cases the matcher must get right

Each row has a labeled pair in `backend/tests/golden_pairs.csv`.

| Person | Where they appear | Verdict | Why it's hard |
|---|---|---|---|
| **Sean O'Brien** (Boston, 5 Beacon St) | northwind NW000771, sunset SC1007, crm 0035000ghi, pos 100244 | **same** | Four name variants; phone matches across three of four. |
| **Maria Hernandez Garcia** (Newark) | crm 0035000abc, ecommerce ec_8841, loyalty LY-50012, pos 100118 | **same** | Two surname orders, two emails, one accented. |
| **Jürgen Müller** (Berlin) | rheinland RH-1001 + RH-1188 | **same** | Same phone+address; one ID is mojibake'd. |
| **David / Dave / D Lee** (Seattle) | ec_9001, ec_9002, ec_9003 | **two same; one unclear** | ec_9003 has `+amazon` alias and no phone — boundary case. |
| **Robert Smith** | pos 100231 (×2), loyalty LY-50019 | **all same** | Within-source duplicate; loyalty maps via FK. |
| **Sean Williams vs Sean Rodriguez** (both Chicago) | northwind | **different** | Negative case. Phone and last name disagree — matcher must not over-merge. |
| **Tony D'Angelo** | sunset SC1021, pos 100250 (mojibake) | **same** | Cross-encoding match where one side is unrecoverable. |
| **Jurgen Schmidt** Berlin vs Köln | rheinland RH-1107 + RH-1123 | **different** | Negative case. Same name, different cities. |

## Issues we noted but do **not** handle

- **No GDPR/erasure flow.**
- **No address standardization** to USPS/CASS. We rely on rapidfuzz.
- **No deduplication of products/SKUs/orders.** Customer only.
- **No language detection** on names. Latin script assumed.
