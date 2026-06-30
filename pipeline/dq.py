"""Challenge 5 — The Tripwire. Deterministic data-quality guardrails.

Every check declares, up front, whether it BREAKS the pipeline or merely ALERTS.
That decision is documented per-check below and mirrored in docs/dq_rules.md.

Why deterministic code and not a prompt (ADR-0005): these are guardrails. A guardrail
that fires "usually" is not a guardrail. Schema contracts, null thresholds, referential
integrity — all of it is exact, so it lives in code. The PreToolUse hook
(hooks/curated_guard.py) calls the same curated contract before any manual write to the
curated zone is allowed.

Severities:
    break  -> abort the build / block the write. Corruption we refuse to propagate.
    alert  -> record and continue. Signal a human should see, not a stop-the-line event.
"""
from __future__ import annotations

import json

from . import common
from .contracts import CURATED_CONTRACT, SOURCE_CONTRACTS

# Rough per-source baselines for the volume-anomaly check (expected row counts).
VOLUME_BASELINE = {
    "pos": 48, "ecommerce": 44, "loyalty": 36, "crm": 30,
    "acq_rheinland": 29, "acq_sunset": 27, "acq_northwind": 33,
}
VOLUME_TOLERANCE = 0.30  # ±30% before we alert


def _result(check, severity, passed, detail):
    return {"check": check, "severity": severity, "passed": passed, "detail": detail}


# --------------------------------------------------------------- pre-curated checks
def check_schema_drift(con) -> list[dict]:
    """BREAK if a source lost its key column; ALERT on any other column delta.
    A missing key column means lineage breaks, so we refuse to build."""
    out = []
    raw_cols = con.execute(
        "SELECT source_system, json_keys(raw_payload) FROM raw_customer"
    ).fetchall()
    seen: dict[str, set] = {}
    for src, keys in raw_cols:
        seen.setdefault(src, set()).update(keys)
    for src, c in SOURCE_CONTRACTS.items():
        expected = set(c["columns"])
        actual = seen.get(src, set()) - {"_overflow"}
        missing = expected - actual
        extra = actual - expected
        key_missing = c["key"] in missing
        if key_missing:
            out.append(_result(f"schema_drift[{src}]", "break", False,
                                f"key column '{c['key']}' missing"))
        elif missing or extra:
            out.append(_result(f"schema_drift[{src}]", "alert", False,
                                f"missing={sorted(missing)} extra={sorted(extra)}"))
        else:
            out.append(_result(f"schema_drift[{src}]", "alert", True, "contract matches"))
    return out


def check_null_explosion(con) -> list[dict]:
    """ALERT if an identity field's null rate is suspiciously high. Does not break:
    sparse fields are normal; we want a human to glance, not to halt."""
    out = []
    total = con.execute("SELECT count(*) FROM conformed_customer").fetchone()[0] or 1
    for field, threshold in [("email", 0.6), ("phone", 0.5), ("dob", 0.7), ("full_name", 0.05)]:
        empty = "" if field == "dob" else f" OR {field}=''"   # dob is DATE, no ''
        nulls = con.execute(
            f"SELECT count(*) FROM conformed_customer WHERE {field} IS NULL{empty}"
        ).fetchone()[0]
        rate = nulls / total
        out.append(_result(f"null_rate[{field}]", "alert", rate <= threshold,
                            f"{rate:.0%} null (threshold {threshold:.0%})"))
    return out


def check_volume_anomaly(con) -> list[dict]:
    out = []
    for src, base in VOLUME_BASELINE.items():
        n = con.execute("SELECT count(*) FROM raw_customer WHERE source_system=?", [src]).fetchone()[0]
        lo, hi = base * (1 - VOLUME_TOLERANCE), base * (1 + VOLUME_TOLERANCE)
        out.append(_result(f"volume[{src}]", "alert", lo <= n <= hi,
                            f"{n} rows (expected ~{base})"))
    return out


def check_referential_integrity(con) -> list[dict]:
    """loyalty.pos_customer_id should resolve to a POS CUST_ID. ALERT only — a dangling
    FK is a data-quality finding, not a reason to refuse the whole load. Sentinels
    (NULL / 999999) are excluded."""
    pos_ids = {r[0] for r in con.execute(
        "SELECT DISTINCT json_extract_string(raw_payload,'$.CUST_ID') FROM raw_customer WHERE source_system='pos'"
    ).fetchall()}
    rows = con.execute(
        "SELECT json_extract_string(raw_payload,'$.pos_customer_id') FROM raw_customer WHERE source_system='loyalty'"
    ).fetchall()
    dangling = [r[0] for r in rows if r[0] and r[0] not in ("NULL", "999999", "") and r[0] not in pos_ids]
    return [_result("ref_integrity[loyalty.pos_customer_id->pos]", "alert", not dangling,
                    f"{len(dangling)} dangling FKs: {dangling[:5]}")]


# --------------------------------------------------------------- curated contract
def check_curated_contract(con) -> list[dict]:
    """BREAK on any curated-contract violation. This is the exact gate the PreToolUse
    hook enforces; curated is the trusted zone analysts read."""
    c = CURATED_CONTRACT
    out = []
    cols = {r[1] for r in con.execute(f"PRAGMA table_info('{c['table']}')").fetchall()}
    missing = set(c["required_columns"]) - cols
    out.append(_result("curated.required_columns", "break", not missing, f"missing={sorted(missing)}"))
    for col in c["non_null"]:
        if col in cols:
            n = con.execute(f"SELECT count(*) FROM {c['table']} WHERE {col} IS NULL").fetchone()[0]
            out.append(_result(f"curated.non_null[{col}]", "break", n == 0, f"{n} nulls"))
    for col, (lo, hi) in c["ranges"].items():
        if col in cols:
            n = con.execute(f"SELECT count(*) FROM {c['table']} WHERE {col} < ? OR {col} > ?", [lo, hi]).fetchone()[0]
            out.append(_result(f"curated.range[{col}]", "break", n == 0, f"{n} out of [{lo},{hi}]"))
    for col in c["unique"]:
        if col in cols:
            dupes = con.execute(
                f"SELECT count(*) FROM (SELECT {col} FROM {c['table']} GROUP BY {col} HAVING count(*)>1)"
            ).fetchone()[0]
            out.append(_result(f"curated.unique[{col}]", "break", dupes == 0, f"{dupes} duplicate keys"))
    # no golden record may have ALL identity anchors null
    n = con.execute(
        f"SELECT count(*) FROM {c['table']} WHERE coalesce(full_name,'')='' AND coalesce(email,'')='' AND coalesce(phone,'')=''"
    ).fetchone()[0]
    out.append(_result("curated.has_identity", "break", n == 0, f"{n} golden records with no identity"))
    return out


# --------------------------------------------------------------- driver
def run(con, stage: str = "pre_curated") -> dict:
    if stage == "pre_curated":
        checks = (check_schema_drift(con) + check_null_explosion(con)
                  + check_volume_anomaly(con) + check_referential_integrity(con))
    else:
        checks = check_curated_contract(con)
    breaches = [c for c in checks if not c["passed"]]
    blocked = any(c["severity"] == "break" and not c["passed"] for c in checks)
    summary = {
        "stage": stage, "checks": len(checks),
        "passed": sum(c["passed"] for c in checks),
        "alerts": sum(1 for c in breaches if c["severity"] == "alert"),
        "breaks": sum(1 for c in breaches if c["severity"] == "break"),
        "blocked": blocked,
    }
    return {"summary": summary, "blocked": blocked, "breaches": breaches, "checks": checks}


if __name__ == "__main__":
    with common.connect() as con:
        print(json.dumps(run(con, "pre_curated")["summary"], indent=2))
