"""Source loaders for the seven Fabrikam systems.

Each loader truncates its raw table and re-loads from the source file.
All five lineage columns are attached: `_source`, `_source_file`, `_source_row`,
`_ingested_at`, `_raw_payload`. The Rheinland loader fixes per-row UTF-8/cp1252
mojibake and records `_encoding_fixed`.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Callable

import duckdb

from pipeline.normalize import utc_now
from pipeline.schemas import ALL_DDL


REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent


# Markers that strongly suggest a cp1252-encoded byte sequence was decoded as
# UTF-8 by mistake (or vice versa).
_MOJIBAKE_MARKERS: tuple[str, ...] = (
    "Ã¼", "Ã¶", "Ã¤", "ÃŸ", "Ã©", "Ã¨", "Ã¡", "Ã³", "Ã±", "Ã„", "Ã–", "Ãœ", "â€",
)


def init_schemas(con: duckdb.DuckDBPyConnection) -> None:
    """Create schemas and all raw/conformed/curated tables."""
    con.execute(ALL_DDL)


def _rel(path: Path) -> str:
    """File path relative to the repo root, forward slashes for portability."""
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _truncate(con: duckdb.DuckDBPyConnection, table: str) -> None:
    con.execute(f"DELETE FROM {table}")


def _insert_rows(
    con: duckdb.DuckDBPyConnection,
    table: str,
    columns: list[str],
    rows: list[tuple[Any, ...]],
) -> None:
    if not rows:
        return
    placeholders = ", ".join(["?"] * len(columns))
    col_list = ", ".join(columns)
    con.executemany(f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})", rows)


def _payload(d: dict[str, Any]) -> str:
    return json.dumps(d, ensure_ascii=False, default=str)


# --- Northwind ---------------------------------------------------------------

def ingest_northwind(con: duckdb.DuckDBPyConnection) -> int:
    src = REPO_ROOT / "acq_northwind" / "legacy_customers.txt"
    rel = _rel(src)
    now = utc_now()

    cols = ["CUSTNO", "CUSTNAME", "ADDR1", "CITY", "ST", "ZIP", "PHONE", "DTADDED", "DTBIRTH", "STATUS"]
    rows: list[tuple[Any, ...]] = []
    with src.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="|")
        for i, rec in enumerate(reader, start=2):  # data starts at line 2
            payload = {k: rec.get(k) for k in cols}
            rows.append((
                rec.get("CUSTNO"), rec.get("CUSTNAME"), rec.get("ADDR1"),
                rec.get("CITY"), rec.get("ST"), rec.get("ZIP"),
                rec.get("PHONE"), rec.get("DTADDED"), rec.get("DTBIRTH"),
                rec.get("STATUS"),
                "acq_northwind", rel, i, now, _payload(payload),
            ))

    _truncate(con, "raw.acq_northwind")
    _insert_rows(
        con, "raw.acq_northwind",
        cols + ["_source", "_source_file", "_source_row", "_ingested_at", "_raw_payload"],
        rows,
    )
    return len(rows)


# --- Rheinland (per-row encoding fix) ---------------------------------------

def _looks_mojibake(s: str) -> bool:
    return any(m in s for m in _MOJIBAKE_MARKERS)


def ingest_rheinland(con: duckdb.DuckDBPyConnection) -> int:
    src = REPO_ROOT / "acq_rheinland" / "kunden.csv"
    rel = _rel(src)
    now = utc_now()

    # Read raw bytes, then decode line-by-line. UTF-8 first; if the decoded line
    # contains mojibake markers we re-decode the bytes as cp1252 and flag it.
    raw_bytes = src.read_bytes()
    line_bytes = raw_bytes.splitlines()
    if not line_bytes:
        return 0

    decoded: list[tuple[str, bool]] = []
    for lb in line_bytes:
        try:
            text = lb.decode("utf-8")
            if _looks_mojibake(text):
                text = lb.decode("cp1252", errors="replace")
                decoded.append((text, True))
            else:
                decoded.append((text, False))
        except UnicodeDecodeError:
            decoded.append((lb.decode("cp1252", errors="replace"), True))

    header_text, _ = decoded[0]
    reader = csv.reader(io.StringIO(header_text), delimiter=";")
    header = next(reader)

    cols = ["Kundennr", "Name", "Strasse", "PLZ", "Ort", "Telefon",
            "Email", "Geburtsdatum", "Umsatz", "Newsletter"]
    rows: list[tuple[Any, ...]] = []
    for i, (text, fixed) in enumerate(decoded[1:], start=2):
        if not text.strip():
            continue
        parts = next(csv.reader(io.StringIO(text), delimiter=";"), [])
        rec = {h: (parts[j] if j < len(parts) else None) for j, h in enumerate(header)}
        payload = {**rec, "_encoding_fixed": fixed}
        rows.append((
            rec.get("Kundennr"), rec.get("Name"), rec.get("Strasse"),
            rec.get("PLZ"), rec.get("Ort"), rec.get("Telefon"),
            rec.get("Email"), rec.get("Geburtsdatum"), rec.get("Umsatz"),
            rec.get("Newsletter"),
            fixed,
            "acq_rheinland", rel, i, now, _payload(payload),
        ))

    _truncate(con, "raw.acq_rheinland")
    _insert_rows(
        con, "raw.acq_rheinland",
        cols + ["_encoding_fixed", "_source", "_source_file", "_source_row", "_ingested_at", "_raw_payload"],
        rows,
    )
    return len(rows)


# --- Sunset (embedded newlines + invalid UTF-8) -----------------------------

def ingest_sunset(con: duckdb.DuckDBPyConnection) -> int:
    src = REPO_ROOT / "acq_sunset" / "catalog_customers.csv"
    rel = _rel(src)
    now = utc_now()

    cols = ["acct", "name", "address", "city", "st", "zip", "phone", "signup_dt", "email", "notes"]
    rows: list[tuple[Any, ...]] = []
    with src.open("r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for i, rec in enumerate(reader, start=2):
            payload = {k: rec.get(k) for k in cols}
            rows.append((
                rec.get("acct"), rec.get("name"), rec.get("address"),
                rec.get("city"), rec.get("st"), rec.get("zip"),
                rec.get("phone"), rec.get("signup_dt"), rec.get("email"),
                rec.get("notes"),
                "acq_sunset", rel, i, now, _payload(payload),
            ))

    _truncate(con, "raw.acq_sunset")
    _insert_rows(
        con, "raw.acq_sunset",
        cols + ["_source", "_source_file", "_source_row", "_ingested_at", "_raw_payload"],
        rows,
    )
    return len(rows)


# --- CRM (BOM, "NULL" strings) ----------------------------------------------

_CRM_RENAME: dict[str, str] = {
    "Contact ID": "contact_id",
    "Account Name": "account_name",
    "Full Name": "full_name",
    "Email": "email",
    "Phone": "phone",
    "Mailing Street": "mailing_street",
    "Mailing City": "mailing_city",
    "Mailing State/Province": "mailing_state",
    "Mailing Zip/Postal Code": "mailing_zip",
    "Date of Birth": "date_of_birth",
    "Lead Source": "lead_source",
    "Created Date": "created_date",
}


def ingest_crm(con: duckdb.DuckDBPyConnection) -> int:
    src = REPO_ROOT / "crm" / "crm_contacts.csv"
    rel = _rel(src)
    now = utc_now()

    cols = list(_CRM_RENAME.values())
    rows: list[tuple[Any, ...]] = []
    with src.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for i, rec in enumerate(reader, start=2):
            renamed = {_CRM_RENAME.get(k, k): v for k, v in rec.items()}
            payload = {k: renamed.get(k) for k in cols}
            rows.append((
                renamed.get("contact_id"), renamed.get("account_name"),
                renamed.get("full_name"), renamed.get("email"), renamed.get("phone"),
                renamed.get("mailing_street"), renamed.get("mailing_city"),
                renamed.get("mailing_state"), renamed.get("mailing_zip"),
                renamed.get("date_of_birth"), renamed.get("lead_source"),
                renamed.get("created_date"),
                "crm", rel, i, now, _payload(payload),
            ))

    _truncate(con, "raw.crm")
    _insert_rows(
        con, "raw.crm",
        cols + ["_source", "_source_file", "_source_row", "_ingested_at", "_raw_payload"],
        rows,
    )
    return len(rows)


# --- Ecommerce (nested JSON) -------------------------------------------------

def ingest_ecommerce(con: duckdb.DuckDBPyConnection) -> int:
    src = REPO_ROOT / "ecommerce" / "customers.json"
    rel = _rel(src)
    now = utc_now()

    cols = [
        "customer_id", "first_name", "last_name", "email", "phone", "created_at",
        "line1", "city", "region", "postal_code", "country",
        "marketing_opt_in", "total_orders",
    ]
    rows: list[tuple[Any, ...]] = []
    with src.open("r", encoding="utf-8") as f:
        records = json.load(f)
    for i, rec in enumerate(records, start=1):
        addr = rec.get("shipping_address") or {}
        flat = {
            "customer_id": rec.get("customer_id"),
            "first_name": rec.get("first_name"),
            "last_name": rec.get("last_name"),
            "email": rec.get("email"),
            "phone": rec.get("phone"),
            "created_at": rec.get("created_at"),
            "line1": addr.get("line1"),
            "city": addr.get("city"),
            "region": addr.get("region"),
            "postal_code": addr.get("postal_code"),
            "country": addr.get("country"),
            "marketing_opt_in": rec.get("marketing_opt_in"),
            "total_orders": rec.get("total_orders"),
        }
        rows.append((
            flat["customer_id"], flat["first_name"], flat["last_name"],
            flat["email"], flat["phone"], flat["created_at"],
            flat["line1"], flat["city"], flat["region"], flat["postal_code"], flat["country"],
            flat["marketing_opt_in"], flat["total_orders"],
            "ecommerce", rel, i, now, _payload(rec),
        ))

    _truncate(con, "raw.ecommerce")
    _insert_rows(
        con, "raw.ecommerce",
        cols + ["_source", "_source_file", "_source_row", "_ingested_at", "_raw_payload"],
        rows,
    )
    return len(rows)


# --- Loyalty -----------------------------------------------------------------

def ingest_loyalty(con: duckdb.DuckDBPyConnection) -> int:
    src = REPO_ROOT / "loyalty" / "loyalty_members.csv"
    rel = _rel(src)
    now = utc_now()

    cols = ["member_id", "full_name", "email", "phone", "tier", "points_balance",
            "enrolled_at", "birth_date", "home_store", "pos_customer_id"]
    rows: list[tuple[Any, ...]] = []
    with src.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for i, rec in enumerate(reader, start=2):
            payload = {k: rec.get(k) for k in cols}
            rows.append((
                rec.get("member_id"), rec.get("full_name"), rec.get("email"),
                rec.get("phone"), rec.get("tier"), rec.get("points_balance"),
                rec.get("enrolled_at"), rec.get("birth_date"),
                rec.get("home_store"), rec.get("pos_customer_id"),
                "loyalty", rel, i, now, _payload(payload),
            ))

    _truncate(con, "raw.loyalty")
    _insert_rows(
        con, "raw.loyalty",
        cols + ["_source", "_source_file", "_source_row", "_ingested_at", "_raw_payload"],
        rows,
    )
    return len(rows)


# --- POS ---------------------------------------------------------------------

def ingest_pos(con: duckdb.DuckDBPyConnection) -> int:
    src = REPO_ROOT / "pos" / "pos_export_2023-11.csv"
    rel = _rel(src)
    now = utc_now()

    cols = ["CUST_ID", "NAME", "PHONE", "EMAIL", "ADDR", "CITY", "STATE",
            "ZIP", "DOB", "LAST_TXN_DATE", "LIFETIME_SPEND"]
    rows: list[tuple[Any, ...]] = []
    with src.open("r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for i, rec in enumerate(reader, start=2):
            payload = {k: rec.get(k) for k in cols}
            rows.append((
                rec.get("CUST_ID"), rec.get("NAME"), rec.get("PHONE"),
                rec.get("EMAIL"), rec.get("ADDR"), rec.get("CITY"),
                rec.get("STATE"), rec.get("ZIP"), rec.get("DOB"),
                rec.get("LAST_TXN_DATE"), rec.get("LIFETIME_SPEND"),
                "pos", rel, i, now, _payload(payload),
            ))

    _truncate(con, "raw.pos")
    _insert_rows(
        con, "raw.pos",
        cols + ["_source", "_source_file", "_source_row", "_ingested_at", "_raw_payload"],
        rows,
    )
    return len(rows)


_LOADERS: list[tuple[str, Callable[[duckdb.DuckDBPyConnection], int]]] = [
    ("acq_northwind", ingest_northwind),
    ("acq_rheinland", ingest_rheinland),
    ("acq_sunset", ingest_sunset),
    ("crm", ingest_crm),
    ("ecommerce", ingest_ecommerce),
    ("loyalty", ingest_loyalty),
    ("pos", ingest_pos),
]


def run_all(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, fn in _LOADERS:
        counts[name] = fn(con)
    return counts
