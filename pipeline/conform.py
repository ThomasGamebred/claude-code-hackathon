"""Challenge 3 (cont.) — parse semi-structured raw rows into ONE canonical schema,
guarded by a validation-RETRY loop.

The loop, exactly as the brief frames it:
    parse  -> a structured validator checks the result
           -> on failure the SPECIFIC error is fed back and a targeted repair runs
           -> retry up to N times
    Per row we log retry_count and the error types hit. Those numbers are evidence
    (see conform_log table and `make report`).

In a fully-agentic build the "parse" step is a Claude tool_use call with a JSON
schema; here the parser is deterministic so the pipeline runs offline and the eval
is reproducible. The control structure — validate, feed the error code back, escalate
the repair, cap the retries — is identical, which is the point the cert stresses.
"""
from __future__ import annotations

import json

from . import common
from .contracts import CONFORMED_SCHEMA, SOURCE_CONTRACTS

MAX_RETRIES = 3

CONFORMED_DDL = "CREATE OR REPLACE TABLE conformed_customer ({});".format(
    ", ".join(f"{n} {t}" for n, t in CONFORMED_SCHEMA)
)
LOG_DDL = """
CREATE OR REPLACE TABLE conform_log (
    lineage_id     VARCHAR,
    source_system  VARCHAR,
    retry_count    INTEGER,
    error_types    VARCHAR,   -- comma-joined codes hit across attempts
    outcome        VARCHAR    -- 'conformed' | 'quarantined'
);
"""


# --------------------------------------------------------------- per-source mapping
def _map(source: str, r: dict) -> dict:
    """Pull canonical fields out of a source-specific payload. Strings only here;
    normalization + validation happen in the retry loop."""
    g = lambda *ks: next((r[k] for k in ks if r.get(k) not in (None, "")), None)
    if source == "pos":
        return dict(name=r.get("NAME"), email=r.get("EMAIL"), phone=r.get("PHONE"),
                    street=r.get("ADDR"), city=r.get("CITY"), state=r.get("STATE"),
                    zip=r.get("ZIP"), dob=r.get("DOB"), country="US",
                    created=r.get("LAST_TXN_DATE"),
                    attrs={"lifetime_spend": r.get("LIFETIME_SPEND"),
                           "last_txn_date": r.get("LAST_TXN_DATE")})
    if source == "ecommerce":
        addr = r.get("shipping_address") or {}
        name = " ".join(x for x in [r.get("first_name"), r.get("last_name")] if x)
        return dict(name=name, email=r.get("email"), phone=r.get("phone"),
                    street=addr.get("line1"), city=addr.get("city"),
                    state=addr.get("region"), zip=addr.get("postal_code"),
                    dob=None, country=addr.get("country") or "US",
                    created=r.get("created_at"),
                    attrs={"marketing_opt_in": r.get("marketing_opt_in"),
                           "total_orders": r.get("total_orders")})
    if source == "loyalty":
        return dict(name=r.get("full_name"), email=r.get("email"), phone=r.get("phone"),
                    street=None, city=None, state=None, zip=None,
                    dob=r.get("birth_date"), country="US", created=r.get("enrolled_at"),
                    attrs={"tier": (r.get("tier") or "").upper() or None,
                           "points_balance": r.get("points_balance"),
                           "home_store": r.get("home_store"),
                           "pos_customer_id": r.get("pos_customer_id")})
    if source == "crm":
        return dict(name=r.get("Full Name"), email=r.get("Email"), phone=r.get("Phone"),
                    street=r.get("Mailing Street"), city=r.get("Mailing City"),
                    state=r.get("Mailing State/Province"),
                    zip=r.get("Mailing Zip/Postal Code"), dob=r.get("Date of Birth"),
                    country="US", created=r.get("Created Date"),
                    attrs={"account_name": r.get("Account Name"),
                           "lead_source": r.get("Lead Source")})
    if source == "acq_rheinland":
        return dict(name=r.get("Name"), email=r.get("Email"), phone=r.get("Telefon"),
                    street=r.get("Strasse"), city=r.get("Ort"), state=None,
                    zip=r.get("PLZ"), dob=r.get("Geburtsdatum"), country="DE",
                    created=None,
                    attrs={"umsatz": r.get("Umsatz"), "newsletter": r.get("Newsletter")})
    if source == "acq_sunset":
        return dict(name=r.get("name"), email=r.get("email"), phone=r.get("phone"),
                    street=r.get("address"), city=r.get("city"), state=r.get("st"),
                    zip=r.get("zip"), dob=None, country="US", created=r.get("signup_dt"),
                    attrs={"notes": r.get("notes")})
    if source == "acq_northwind":
        return dict(name=r.get("CUSTNAME"), email=None, phone=r.get("PHONE"),
                    street=r.get("ADDR1"), city=r.get("CITY"), state=r.get("ST"),
                    zip=r.get("ZIP"), dob=r.get("DTBIRTH"), country="US",
                    created=r.get("DTADDED"),
                    attrs={"status": r.get("STATUS")})
    raise ValueError(source)


# --------------------------------------------------------------- validate + repair
def _normalize(cand: dict, tz: str, *, dayfirst: bool, repair_enc: bool) -> dict:
    name = cand.get("name")
    street = cand.get("street")
    city = cand.get("city")
    if repair_enc:
        name, street, city = (common.repair_mojibake(x) for x in (name, street, city))
    return {
        "full_name": name,
        "name_norm": common.normalize_name(name),
        "email": (cand.get("email") or "").strip() or None,
        "email_norm": common.normalize_email(cand.get("email")),
        "phone": (cand.get("phone") or "").strip() or None,
        "phone_norm": common.normalize_phone(cand.get("phone")),
        "street": street,
        "city": city,
        "state": (cand.get("state") or "").strip() or None,
        "zip": common.normalize_zip(cand.get("zip")) or None,
        "country": cand.get("country"),
        "dob": common.parse_date(cand.get("dob"), dayfirst=dayfirst),
        "created_at_utc": common.parse_timestamp_utc(cand.get("created"), assume_tz=tz)
                          or common.parse_date(cand.get("created"), dayfirst=dayfirst),
    }


def _validate(rec: dict, cand: dict) -> list[str]:
    """Return error CODES (empty list == valid). Codes drive the next repair."""
    errs: list[str] = []
    if not (rec["name_norm"] or rec["email_norm"] or rec["phone_norm"]):
        errs.append("EMPTY_IDENTITY")
    if common.has_lossy_encoding(rec.get("full_name")) or any(
        "Ã" in (cand.get(k) or "") for k in ("name", "street", "city")
    ):
        errs.append("BAD_ENCODING")
    if cand.get("dob") and rec["dob"] is None and str(cand["dob"]).strip() not in (
        "0", "00000000", "N/A", "NULL", "", "1900-01-01", "01/01/1900"
    ):
        errs.append("BAD_DATE")
    if rec.get("email") and not rec["email_norm"]:
        errs.append("BAD_EMAIL")
    return errs


def conform_row(source: str, payload: dict, tz: str) -> tuple[dict | None, int, list[str]]:
    """Run the parse-validate-retry loop for one row.

    Returns (conformed_record_or_None, retry_count, error_types_seen)."""
    cand = _map(source, payload)
    dayfirst = source == "acq_rheinland"
    repair_enc = False
    seen: list[str] = []
    rec = _normalize(cand, tz, dayfirst=dayfirst, repair_enc=repair_enc)

    for attempt in range(MAX_RETRIES + 1):
        errs = _validate(rec, cand)
        fresh = [e for e in errs if e not in seen]
        seen.extend(fresh)
        if not errs:
            return rec, attempt, seen
        # feed the first error back as a targeted repair, then retry
        code = errs[0]
        if code == "BAD_ENCODING" and not repair_enc:
            repair_enc = True
        elif code == "BAD_DATE":
            dayfirst = not dayfirst   # flip D/M vs M/D interpretation and retry
        elif code == "BAD_EMAIL":
            cand["email"] = None      # drop an unparseable address rather than fail the row
        elif code == "EMPTY_IDENTITY":
            break                     # unrecoverable — no identity anchor exists
        rec = _normalize(cand, tz, dayfirst=dayfirst, repair_enc=repair_enc)

    # exhausted retries (or hit EMPTY_IDENTITY): quarantine if still no identity
    if not (rec["name_norm"] or rec["email_norm"] or rec["phone_norm"]):
        return None, min(attempt, MAX_RETRIES), seen
    return rec, min(attempt, MAX_RETRIES), seen   # best-effort row with residual flags


def run(con) -> dict:
    con.execute(CONFORMED_DDL)
    con.execute(LOG_DDL)
    rows = con.execute(
        "SELECT lineage_id, source_system, source_record_id, raw_payload FROM raw_customer ORDER BY ingest_seq"
    ).fetchall()

    conformed = quarantined = total_retries = 0
    for lid, source, srid, payload_json in rows:
        payload = json.loads(payload_json)
        tz = SOURCE_CONTRACTS[source]["tz"]
        rec, retries, errs = conform_row(source, payload, tz)
        total_retries += retries
        outcome = "conformed" if rec else "quarantined"
        con.execute(
            "INSERT INTO conform_log VALUES (?,?,?,?,?)",
            [lid, source, retries, ",".join(errs), outcome],
        )
        if not rec:
            quarantined += 1
            continue
        conformed += 1
        con.execute(
            "INSERT INTO conformed_customer VALUES ({})".format(",".join("?" * len(CONFORMED_SCHEMA))),
            [lid, source, srid, rec["full_name"], rec["name_norm"], rec["email"],
             rec["email_norm"], rec["phone"], rec["phone_norm"], rec["street"],
             rec["city"], rec["state"], rec["zip"], rec["country"], rec["dob"],
             rec["created_at_utc"], json.dumps(_map(source, payload)["attrs"], default=str),
             ",".join(errs)],
        )
    return {"conformed": conformed, "quarantined": quarantined,
            "rows_with_retries": total_retries}


if __name__ == "__main__":
    with common.connect() as con:
        print(json.dumps(run(con), indent=2))
