"""Per-source conformers: raw -> conformed.customer (and conformed._reject).

Each conformer pulls the raw rows, runs them through the normalizers, and either
emits a canonical row to `conformed.customer` or routes the row to `_reject`
with a specific `reject_field` + `reject_reason`. Validation-retry happens
inside `normalize.parse_date`.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import duckdb

from pipeline.normalize import (
    nfkd_strip_accents,
    normalize_email,
    normalize_name,
    normalize_phone,
    pad_us_zip,
    parse_date,
    split_full_name,
    utc_now,
)


# Test/fake records we never want to surface to analysts. Match is substring
# on the normalized lowercase full name.
_TEST_BLOCKLIST: tuple[str, ...] = (
    "test test do not use",
    "mickey mouse",
    "vandelay art",
    "vandelay, art",
    "donald duck",
)


_MOJIBAKE_LOSSY_MARKERS: tuple[str, ...] = ("�", "?¿", "¿")


def _is_test_record(full_name: str | None) -> bool:
    if not full_name:
        return False
    n = nfkd_strip_accents(full_name).lower()
    return any(pat in n for pat in _TEST_BLOCKLIST)


def _flags_to_str(flags: dict[str, bool]) -> str:
    return ",".join(sorted(k for k, v in flags.items() if v))


def _normalized_full(first: str | None, last: str | None) -> str | None:
    parts = [p for p in (first, last) if p]
    if not parts:
        return None
    return normalize_name(" ".join(parts))


def _wipe_conformed(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("DELETE FROM conformed.customer")
    con.execute("DELETE FROM conformed._reject")


_CONFORMED_COLUMNS: tuple[str, ...] = (
    "_source", "_source_id", "_source_row", "_source_tz", "_encoding_lossy",
    "first_name", "last_name", "full_name_normalized",
    "email_normalized", "phone_e164", "phone_ext",
    "street", "city", "region", "postal_code", "country",
    "birth_date", "created_at_utc", "field_quality_flags",
)


def _insert_conformed(con: duckdb.DuckDBPyConnection, rows: list[tuple[Any, ...]]) -> None:
    if not rows:
        return
    placeholders = ", ".join(["?"] * len(_CONFORMED_COLUMNS))
    cols = ", ".join(_CONFORMED_COLUMNS)
    con.executemany(
        f"INSERT INTO conformed.customer ({cols}) VALUES ({placeholders})",
        rows,
    )


def _insert_rejects(con: duckdb.DuckDBPyConnection, rows: list[tuple[Any, ...]]) -> None:
    if not rows:
        return
    con.executemany(
        "INSERT INTO conformed._reject (_source, _source_id, _source_row, reject_field, reject_reason, raw_payload, rejected_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


# --- Northwind --------------------------------------------------------------

def conform_northwind(con: duckdb.DuckDBPyConnection) -> tuple[int, int]:
    rows = con.execute(
        "SELECT CUSTNO, CUSTNAME, ADDR1, CITY, ST, ZIP, PHONE, DTADDED, DTBIRTH, STATUS, "
        "       _source_row, _raw_payload FROM raw.acq_northwind"
    ).fetchall()
    now = utc_now()
    out: list[tuple[Any, ...]] = []
    rej: list[tuple[Any, ...]] = []

    for r in rows:
        custno, name, addr, city, st, zip_, phone, dtadded, dtbirth, status, src_row, payload = r
        if _is_test_record(name):
            rej.append(("acq_northwind", custno or "", src_row, "name", "test_record", payload, now))
            continue
        first, last = split_full_name(name)
        full_norm = _normalized_full(first, last)
        email = None
        phone_e164, phone_ext = normalize_phone(phone, default_region="US")
        zip_out, padded = pad_us_zip(zip_)
        bdate = parse_date(dtbirth, formats=("%Y%m%d",))
        created = parse_date(dtadded, formats=("%Y%m%d",))
        flags = {
            "name_truncated": bool(name and len(str(name).rstrip()) == 20 and " " in str(name)),
            "phone_invalid": bool(phone) and phone_e164 is None,
            "zip_padded": padded,
            "dob_zero_date": str(dtbirth).strip() == "00000000",
        }
        out.append((
            "acq_northwind", custno or f"NW-row-{src_row}", src_row, "UNKNOWN", False,
            first, last, full_norm, email, phone_e164, phone_ext,
            addr, city, (st or "").upper() or None, zip_out, "US",
            bdate,
            datetime.combine(created, datetime.min.time()) if created else None,
            _flags_to_str(flags),
        ))
    _insert_conformed(con, out)
    _insert_rejects(con, rej)
    return len(out), len(rej)


# --- Rheinland --------------------------------------------------------------

def conform_rheinland(con: duckdb.DuckDBPyConnection) -> tuple[int, int]:
    rows = con.execute(
        "SELECT Kundennr, Name, Strasse, PLZ, Ort, Telefon, Email, Geburtsdatum, "
        "       Umsatz, Newsletter, _encoding_fixed, _source_row, _raw_payload "
        "FROM raw.acq_rheinland"
    ).fetchall()
    now = utc_now()
    out: list[tuple[Any, ...]] = []
    rej: list[tuple[Any, ...]] = []

    for r in rows:
        knr, name, strasse, plz, ort, tel, email, gdat, umsatz, news, fixed, src_row, payload = r
        if _is_test_record(name):
            rej.append(("acq_rheinland", knr or "", src_row, "name", "test_record", payload, now))
            continue
        first, last = split_full_name(name)
        full_norm = _normalized_full(first, last)
        email_n = normalize_email(email)
        phone_e164, phone_ext = normalize_phone(tel, default_region="DE")
        bdate = parse_date(gdat, formats=("%d.%m.%Y", "%Y-%m-%d"))
        if gdat and bdate is None:
            rej.append(("acq_rheinland", knr or "", src_row, "Geburtsdatum", "invalid_date", payload, now))
            continue
        encoding_lossy = bool(fixed) or any(m in (name or "") for m in _MOJIBAKE_LOSSY_MARKERS)
        flags = {
            "encoding_lossy": encoding_lossy,
            "phone_invalid": bool(tel) and phone_e164 is None,
        }
        out.append((
            "acq_rheinland", knr or f"RH-row-{src_row}", src_row, "Europe/Berlin", encoding_lossy,
            first, last, full_norm, email_n, phone_e164, phone_ext,
            strasse, ort, "DE", plz, "DE",
            bdate, None, _flags_to_str(flags),
        ))
    _insert_conformed(con, out)
    _insert_rejects(con, rej)
    return len(out), len(rej)


# --- Sunset -----------------------------------------------------------------

def conform_sunset(con: duckdb.DuckDBPyConnection) -> tuple[int, int]:
    rows = con.execute(
        "SELECT acct, name, address, city, st, zip, phone, signup_dt, email, notes, "
        "       _source_row, _raw_payload FROM raw.acq_sunset"
    ).fetchall()
    now = utc_now()
    out: list[tuple[Any, ...]] = []
    rej: list[tuple[Any, ...]] = []

    for r in rows:
        acct, name, addr, city, st, zip_, phone, signup, email, notes, src_row, payload = r
        if _is_test_record(name):
            rej.append(("acq_sunset", acct or "", src_row, "name", "test_record", payload, now))
            continue
        # All-NULL row guard.
        non_null = sum(1 for v in (name, addr, city, st, zip_, phone, signup, email) if v)
        if non_null == 0:
            rej.append(("acq_sunset", acct or "", src_row, "*", "all_null", payload, now))
            continue
        first, last = split_full_name(name)
        full_norm = _normalized_full(first, last)
        email_n = normalize_email(email)
        phone_e164, phone_ext = normalize_phone(phone, default_region="US")
        signup_d = parse_date(signup)
        zip_out, padded = pad_us_zip(zip_)
        encoding_lossy = any(m in (name or "") for m in _MOJIBAKE_LOSSY_MARKERS) or "�" in (addr or "")
        flags = {
            "encoding_lossy": encoding_lossy,
            "phone_invalid": bool(phone) and phone_e164 is None,
            "zip_padded": padded,
        }
        out.append((
            "acq_sunset", acct or f"SC-row-{src_row}", src_row, "America/New_York", encoding_lossy,
            first, last, full_norm, email_n, phone_e164, phone_ext,
            addr, city, (st or "").upper() or None, zip_out, "US",
            None,
            datetime.combine(signup_d, datetime.min.time()) if signup_d else None,
            _flags_to_str(flags),
        ))
    _insert_conformed(con, out)
    _insert_rejects(con, rej)
    return len(out), len(rej)


# --- CRM --------------------------------------------------------------------

def _crm_clean_null(v: str | None) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if s.upper() == "NULL" or s == "":
        return None
    return s


def conform_crm(con: duckdb.DuckDBPyConnection) -> tuple[int, int]:
    rows = con.execute(
        "SELECT contact_id, full_name, email, phone, mailing_street, mailing_city, "
        "       mailing_state, mailing_zip, date_of_birth, created_date, "
        "       _source_row, _raw_payload FROM raw.crm"
    ).fetchall()
    now = utc_now()
    out: list[tuple[Any, ...]] = []
    rej: list[tuple[Any, ...]] = []

    for r in rows:
        (cid, full, email, phone, street, city, state, zip_, dob, created,
         src_row, payload) = r
        full = _crm_clean_null(full)
        email = _crm_clean_null(email)
        phone = _crm_clean_null(phone)
        street = _crm_clean_null(street)
        city = _crm_clean_null(city)
        state = _crm_clean_null(state)
        zip_ = _crm_clean_null(zip_)
        dob = _crm_clean_null(dob)
        created = _crm_clean_null(created)

        if _is_test_record(full):
            rej.append(("crm", cid or "", src_row, "full_name", "test_record", payload, now))
            continue
        first, last = split_full_name(full)
        full_norm = _normalized_full(first, last)
        email_n = normalize_email(email)
        phone_e164, phone_ext = normalize_phone(phone, default_region="US")
        bdate = parse_date(dob, formats=("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"))
        if dob and bdate is None:
            rej.append(("crm", cid or "", src_row, "date_of_birth", "invalid_date", payload, now))
            continue
        cdate = parse_date(created, formats=("%m/%d/%y", "%m/%d/%Y"))
        zip_out, padded = pad_us_zip(zip_)
        flags = {
            "phone_invalid": bool(phone) and phone_e164 is None,
            "zip_padded": padded,
        }
        out.append((
            "crm", cid or f"CRM-row-{src_row}", src_row, "America/New_York", False,
            first, last, full_norm, email_n, phone_e164, phone_ext,
            street, city, (state or "").upper() or None, zip_out, "US",
            bdate,
            datetime.combine(cdate, datetime.min.time()) if cdate else None,
            _flags_to_str(flags),
        ))
    _insert_conformed(con, out)
    _insert_rejects(con, rej)
    return len(out), len(rej)


# --- Ecommerce --------------------------------------------------------------

def conform_ecommerce(con: duckdb.DuckDBPyConnection) -> tuple[int, int]:
    rows = con.execute(
        "SELECT customer_id, first_name, last_name, email, phone, created_at, "
        "       line1, city, region, postal_code, country, "
        "       _source_row, _raw_payload FROM raw.ecommerce"
    ).fetchall()
    now = utc_now()
    out: list[tuple[Any, ...]] = []
    rej: list[tuple[Any, ...]] = []

    for r in rows:
        (cid, fn, ln, email, phone, created, line1, city, region, zip_, country,
         src_row, payload) = r
        if _is_test_record(f"{fn or ''} {ln or ''}"):
            rej.append(("ecommerce", cid or "", src_row, "full_name", "test_record", payload, now))
            continue
        first = (fn or "").strip().title() or None
        last = (ln or "").strip().title() or None
        full_norm = _normalized_full(first, last)
        email_n = normalize_email(email)
        default_region = "US" if (country or "").upper() in ("", "US", "USA") else (country or "US").upper()[:2]
        phone_e164, phone_ext = normalize_phone(phone, default_region=default_region or "US")
        created_dt: datetime | None = None
        if created:
            d = parse_date(created)
            if d is None:
                rej.append(("ecommerce", cid or "", src_row, "created_at", "invalid_date", payload, now))
                continue
            created_dt = datetime.combine(d, datetime.min.time())
        flags = {
            "phone_invalid": bool(phone) and phone_e164 is None,
        }
        out.append((
            "ecommerce", cid or f"EC-row-{src_row}", src_row, "UTC", False,
            first, last, full_norm, email_n, phone_e164, phone_ext,
            line1, city, (region or "").upper() or None, zip_, country,
            None, created_dt, _flags_to_str(flags),
        ))
    _insert_conformed(con, out)
    _insert_rejects(con, rej)
    return len(out), len(rej)


# --- Loyalty ----------------------------------------------------------------

def conform_loyalty(con: duckdb.DuckDBPyConnection) -> tuple[int, int]:
    rows = con.execute(
        "SELECT member_id, full_name, email, phone, tier, points_balance, "
        "       enrolled_at, birth_date, home_store, pos_customer_id, "
        "       _source_row, _raw_payload FROM raw.loyalty"
    ).fetchall()
    now = utc_now()
    out: list[tuple[Any, ...]] = []
    rej: list[tuple[Any, ...]] = []

    for r in rows:
        (mid, full, email, phone, tier, pts, enrolled, bdate, store, posfk,
         src_row, payload) = r
        if _is_test_record(full):
            rej.append(("loyalty", mid or "", src_row, "full_name", "test_record", payload, now))
            continue
        first, last = split_full_name(full)
        full_norm = _normalized_full(first, last)
        email_n = normalize_email(email)
        phone_e164, phone_ext = normalize_phone(phone, default_region="US")
        bd = parse_date(bdate, formats=("%Y-%m-%d", "%m/%d/%Y"))
        if bdate and bd is None and str(bdate).strip() not in ("0000-00-00",):
            rej.append(("loyalty", mid or "", src_row, "birth_date", "invalid_date", payload, now))
            continue
        enrolled_dt = None
        if enrolled:
            d = parse_date(enrolled)
            if d is not None:
                enrolled_dt = datetime.combine(d, datetime.min.time())

        fk_sentinel = False
        if posfk is not None:
            fkv = str(posfk).strip()
            if fkv in ("", "999999", "NULL"):
                fk_sentinel = True

        flags = {
            "phone_invalid": bool(phone) and phone_e164 is None,
            "dob_zero_date": str(bdate).strip() == "0000-00-00",
            "fk_sentinel": fk_sentinel,
        }
        out.append((
            "loyalty", mid or f"LY-row-{src_row}", src_row, "America/New_York", False,
            first, last, full_norm, email_n, phone_e164, phone_ext,
            None, None, None, None, "US",
            bd, enrolled_dt, _flags_to_str(flags),
        ))
    _insert_conformed(con, out)
    _insert_rejects(con, rej)
    return len(out), len(rej)


# --- POS --------------------------------------------------------------------

def conform_pos(con: duckdb.DuckDBPyConnection) -> tuple[int, int]:
    rows = con.execute(
        "SELECT CUST_ID, NAME, PHONE, EMAIL, ADDR, CITY, STATE, ZIP, DOB, "
        "       LAST_TXN_DATE, LIFETIME_SPEND, _source_row, _raw_payload "
        "FROM raw.pos"
    ).fetchall()
    now = utc_now()
    out: list[tuple[Any, ...]] = []
    rej: list[tuple[Any, ...]] = []

    for r in rows:
        (cid, name, phone, email, addr, city, state, zip_, dob, last_txn, spend,
         src_row, payload) = r
        if _is_test_record(name):
            rej.append(("pos", f"{cid}:{src_row}" if cid else "", src_row, "name", "test_record", payload, now))
            continue
        try:
            spend_v = float(spend) if spend not in (None, "") else 0.0
        except (TypeError, ValueError):
            spend_v = 0.0
        if spend_v > 1_000_000:
            rej.append(("pos", f"{cid}:{src_row}", src_row, "LIFETIME_SPEND", "spend_outlier", payload, now))
            continue

        first, last = split_full_name(name)
        # DOB sanity: reject impossible (year > 2030 or < 1900).
        bdate = parse_date(dob, formats=("%m/%d/%Y", "%Y-%m-%d"))
        if dob and bdate is None:
            rej.append(("pos", f"{cid}:{src_row}", src_row, "DOB", "invalid_date", payload, now))
            continue
        if bdate and (bdate.year < 1900 or bdate.year > 2030):
            rej.append(("pos", f"{cid}:{src_row}", src_row, "DOB", "dob_out_of_range", payload, now))
            continue

        full_norm = _normalized_full(first, last)
        email_n = normalize_email(email)
        phone_e164, phone_ext = normalize_phone(phone, default_region="US")
        zip_out, padded = pad_us_zip(zip_)
        encoding_lossy = "�" in (name or "") or "�" in (addr or "")
        last_txn_d = parse_date(last_txn, formats=("%m/%d/%Y", "%Y-%m-%d"))
        flags = {
            "encoding_lossy": encoding_lossy,
            "phone_invalid": bool(phone) and phone_e164 is None,
            "zip_padded": padded,
        }
        # Within-source duplicates on cust_id — disambiguate via row number.
        source_id = f"{cid}:{src_row}"
        out.append((
            "pos", source_id, src_row, "America/Chicago", encoding_lossy,
            first, last, full_norm, email_n, phone_e164, phone_ext,
            addr, city, (state or "").upper() or None, zip_out, "US",
            bdate,
            datetime.combine(last_txn_d, datetime.min.time()) if last_txn_d else None,
            _flags_to_str(flags),
        ))
    _insert_conformed(con, out)
    _insert_rejects(con, rej)
    return len(out), len(rej)


_CONFORMERS: list[tuple[str, Callable[[duckdb.DuckDBPyConnection], tuple[int, int]]]] = [
    ("acq_northwind", conform_northwind),
    ("acq_rheinland", conform_rheinland),
    ("acq_sunset", conform_sunset),
    ("crm", conform_crm),
    ("ecommerce", conform_ecommerce),
    ("loyalty", conform_loyalty),
    ("pos", conform_pos),
]


def run_all(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, int]]:
    _wipe_conformed(con)
    result: dict[str, dict[str, int]] = {}
    for name, fn in _CONFORMERS:
        kept, rejected = fn(con)
        result[name] = {"kept": kept, "rejected": rejected}
    return result
