"""Schema contracts.

A *contract* is what a producer promises: the columns, the key, the encoding, the
shape. Contracts are the single source of truth for three things:

  1. Ingestion reads them to know how to parse each source.
  2. The Tripwire (dq.py) reads them to detect schema drift.
  3. The PreToolUse hook reads the CURATED contract to block bad writes to the
     curated zone (deterministic guardrail — see ADR-0005).

The catalog (catalog/*.md) links each analyst-facing entry back to the contract
here, so an analyst can see exactly what the producer is promising.
"""
from __future__ import annotations

# Each source contract: how to read it + which fields exist + the natural key.
# `tz` documents the wall-clock zone of naive timestamps (the loyalty bug).
SOURCE_CONTRACTS: dict[str, dict] = {
    "pos": {
        "path": "pos/pos_export_2023-11.csv",
        "format": "csv",
        "delimiter": ",",
        "encoding": "cp1252",          # the � bytes are cp1252 mis-encoded
        "key": "CUST_ID",
        "columns": ["CUST_ID", "NAME", "PHONE", "EMAIL", "ADDR", "CITY", "STATE",
                     "ZIP", "DOB", "LAST_TXN_DATE", "LIFETIME_SPEND"],
        "tz": "America/Chicago",
        "notes": "Register export. Name is 'LAST, FIRST'. Zip loses leading zero. "
                 "Same CUST_ID can appear twice (multiple register profiles).",
    },
    "ecommerce": {
        "path": "ecommerce/customers.json",
        "format": "json",
        "encoding": "utf-8",
        "key": "customer_id",
        "columns": ["customer_id", "first_name", "last_name", "email", "phone",
                     "created_at", "shipping_address", "marketing_opt_in", "total_orders"],
        "tz": "UTC",                   # created_at carries a Z, already UTC
        "notes": "Web store. Nested shipping_address. created_at is ISO-8601 Z.",
    },
    "loyalty": {
        "path": "loyalty/loyalty_members.csv",
        "format": "csv",
        "delimiter": ",",
        "encoding": "utf-8",
        "key": "member_id",
        "columns": ["member_id", "full_name", "email", "phone", "tier",
                     "points_balance", "enrolled_at", "birth_date", "home_store",
                     "pos_customer_id"],
        "tz": "America/Chicago",        # enrolled_at is naive local store time -> THE TIMEZONE BUG
        "notes": "Loyalty program. enrolled_at is naive store-local time. "
                 "tier casing is inconsistent. pos_customer_id is a real FK into POS "
                 "(may be NULL/999999 sentinel).",
    },
    "crm": {
        "path": "crm/crm_contacts.csv",
        "format": "csv",
        "delimiter": ",",
        "encoding": "utf-8-sig",        # leading BOM
        "key": "Contact ID",
        "columns": ["Contact ID", "Account Name", "Full Name", "Email", "Phone",
                     "Mailing Street", "Mailing City", "Mailing State/Province",
                     "Mailing Zip/Postal Code", "Date of Birth", "Lead Source", "Created Date"],
        "tz": "America/New_York",
        "notes": "Salesforce-style export. BOM, quoted everything, M/D/YY dates, "
                 "literal 'NULL' strings, junk accounts (Ghost Holdings).",
    },
    "acq_rheinland": {
        "path": "acq_rheinland/kunden.csv",
        "format": "csv",
        "delimiter": ";",
        "encoding": "utf-8",
        "key": "Kundennr",
        "columns": ["Kundennr", "Name", "Strasse", "PLZ", "Ort", "Telefon",
                     "Email", "Geburtsdatum", "Umsatz", "Newsletter"],
        "tz": "Europe/Berlin",
        "notes": "German acquisition. Semicolon-delimited, German dates (D.M.Y) & "
                 "money (1.234,56). Contains mojibake duplicates of clean rows.",
    },
    "acq_sunset": {
        "path": "acq_sunset/catalog_customers.csv",
        "format": "csv",
        "delimiter": ",",
        "encoding": "utf-8",
        "key": "acct",
        "columns": ["acct", "name", "address", "city", "st", "zip", "phone",
                     "signup_dt", "email", "notes"],
        "tz": "America/New_York",
        "notes": "Catalog acquisition. Excel-serial dates mixed with M/D/Y, "
                 "embedded newlines in quoted fields, an all-empty row, encoding loss.",
    },
    "acq_northwind": {
        "path": "acq_northwind/legacy_customers.txt",
        "format": "pipe",
        "delimiter": "|",
        "encoding": "utf-8",
        "key": "CUSTNO",
        "columns": ["CUSTNO", "CUSTNAME", "ADDR1", "CITY", "ST", "ZIP", "PHONE",
                     "DTADDED", "DTBIRTH", "STATUS"],
        "tz": "America/New_York",
        "notes": "Legacy AS/400 dump. Pipe-delimited, fixed-ish width, names "
                 "truncated to ~20 chars (HALPERT JAMES MICHAE), YYYYMMDD dates, "
                 "00000000 as null date.",
    },
}

# The canonical conformed-customer schema. Every source maps onto this.
CONFORMED_SCHEMA: list[tuple[str, str]] = [
    ("lineage_id", "VARCHAR"),       # -> raw row
    ("source_system", "VARCHAR"),
    ("source_record_id", "VARCHAR"),
    ("full_name", "VARCHAR"),
    ("name_norm", "VARCHAR"),        # normalized blocking/match key
    ("email", "VARCHAR"),
    ("email_norm", "VARCHAR"),
    ("phone", "VARCHAR"),
    ("phone_norm", "VARCHAR"),
    ("street", "VARCHAR"),
    ("city", "VARCHAR"),
    ("state", "VARCHAR"),
    ("zip", "VARCHAR"),
    ("country", "VARCHAR"),
    ("dob", "DATE"),
    ("created_at_utc", "TIMESTAMPTZ"),
    ("attributes", "JSON"),          # source-specific extras (tier, spend, opt-in...)
    ("dq_flags", "VARCHAR"),         # comma-joined flags raised during conform
]

# The CURATED golden-record contract. The PreToolUse hook enforces THIS before any
# write into the curated zone is allowed (ADR-0005).
CURATED_CONTRACT: dict = {
    "table": "curated_customer",
    "required_columns": [
        "golden_id", "full_name", "email", "phone", "match_confidence",
        "member_count", "member_lineage_ids", "field_provenance", "field_confidence",
    ],
    "non_null": ["golden_id", "match_confidence", "member_count"],
    "ranges": {"match_confidence": (0.0, 1.0), "member_count": (1, 100)},
    "unique": ["golden_id"],
}
