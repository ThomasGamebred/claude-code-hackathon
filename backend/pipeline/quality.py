"""Deterministic quality guardrails. Logic lives here, never in prompts."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import duckdb

from pipeline.schemas import CONTRACTS, SourceContract


class Severity(str, Enum):
    BLOCK = "BLOCK"
    ALERT = "ALERT"


@dataclass
class CheckResult:
    name: str
    severity: Severity
    passed: bool
    detail: str
    metrics: dict[str, Any] = field(default_factory=dict)


class QualityFailure(Exception):
    def __init__(self, failures: list[CheckResult]) -> None:
        self.failures = failures
        super().__init__("Quality check(s) BLOCK: " + ", ".join(f.name for f in failures))


def _raw_columns(con: duckdb.DuckDBPyConnection, source: str) -> set[str]:
    rows = con.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'raw' AND table_name = ?",
        [source],
    ).fetchall()
    return {r[0] for r in rows}


def check_schema_drift(con: duckdb.DuckDBPyConnection) -> CheckResult:
    missing: dict[str, list[str]] = {}
    extra: dict[str, list[str]] = {}
    for contract in CONTRACTS:
        present = _raw_columns(con, contract.name)
        expected = set(contract.columns)
        miss = sorted(expected - present)
        ext = sorted(present - expected - {"_source", "_source_file", "_source_row",
                                            "_ingested_at", "_raw_payload",
                                            "_encoding_fixed"})
        if miss:
            missing[contract.name] = miss
        if ext:
            extra[contract.name] = ext

    passed = not missing  # extras tolerated; missing fail.
    detail = "no drift" if passed else f"missing columns: {missing}"
    return CheckResult(
        name="schema_drift",
        severity=Severity.BLOCK,
        passed=passed,
        detail=detail,
        metrics={"missing": missing, "extra": extra},
    )


def check_null_explosion(
    con: duckdb.DuckDBPyConnection,
    threshold: float = 0.95,
) -> CheckResult:
    sources = [c.name for c in CONTRACTS]
    explosions: dict[str, dict[str, float]] = {}
    for src in sources:
        row = con.execute(
            "SELECT "
            "  COUNT(*) AS total, "
            "  SUM(CASE WHEN first_name IS NULL THEN 1 ELSE 0 END) AS f, "
            "  SUM(CASE WHEN last_name IS NULL THEN 1 ELSE 0 END) AS l, "
            "  SUM(CASE WHEN phone_e164 IS NULL THEN 1 ELSE 0 END) AS p, "
            "  SUM(CASE WHEN email_normalized IS NULL THEN 1 ELSE 0 END) AS e "
            "FROM conformed.customer WHERE _source = ?",
            [src],
        ).fetchone()
        total = row[0] or 0
        if total == 0:
            continue
        rates = {
            "first_name": (row[1] or 0) / total,
            "last_name": (row[2] or 0) / total,
            "phone_e164": (row[3] or 0) / total,
            "email_normalized": (row[4] or 0) / total,
        }
        offenders = {k: v for k, v in rates.items() if v >= threshold}
        if offenders:
            explosions[src] = offenders

    passed = not explosions
    detail = "no null explosion" if passed else f"sources over threshold: {list(explosions)}"
    return CheckResult(
        name="null_explosion",
        severity=Severity.ALERT,
        passed=passed,
        detail=detail,
        metrics={"threshold": threshold, "offenders": explosions},
    )


def check_volume(
    con: duckdb.DuckDBPyConnection,
    baseline: dict[str, int] | None = None,
    tolerance: float = 0.30,
) -> CheckResult:
    counts: dict[str, int] = {}
    deltas: dict[str, float] = {}
    for c in CONTRACTS:
        n = con.execute(f"SELECT COUNT(*) FROM raw.{c.name}").fetchone()[0] or 0
        counts[c.name] = n
        if baseline and c.name in baseline and baseline[c.name] > 0:
            d = (n - baseline[c.name]) / baseline[c.name]
            if abs(d) > tolerance:
                deltas[c.name] = d
    passed = not deltas
    detail = "no volume anomaly" if passed else f"deltas exceed tolerance: {deltas}"
    return CheckResult(
        name="volume",
        severity=Severity.ALERT,
        passed=passed,
        detail=detail,
        metrics={"counts": counts, "deltas": deltas, "tolerance": tolerance},
    )


def check_referential_integrity(con: duckdb.DuckDBPyConnection) -> CheckResult:
    rows = con.execute(
        "SELECT pos_customer_id FROM raw.loyalty WHERE pos_customer_id IS NOT NULL "
        "  AND TRIM(pos_customer_id) NOT IN ('', 'NULL', '999999')"
    ).fetchall()
    pos_ids_loy = {str(r[0]).strip() for r in rows if r[0]}
    pos_ids_raw = {
        str(r[0]).strip()
        for r in con.execute("SELECT DISTINCT CUST_ID FROM raw.pos").fetchall()
        if r[0]
    }
    orphans = sorted(pos_ids_loy - pos_ids_raw)
    passed = not orphans
    detail = "all loyalty FKs resolve" if passed else f"{len(orphans)} orphaned FK(s)"
    return CheckResult(
        name="referential_integrity",
        severity=Severity.ALERT,
        passed=passed,
        detail=detail,
        metrics={"orphans": orphans, "checked": len(pos_ids_loy)},
    )


def run_all(con: duckdb.DuckDBPyConnection) -> list[CheckResult]:
    return [
        check_schema_drift(con),
        check_null_explosion(con),
        check_volume(con),
        check_referential_integrity(con),
    ]


def assert_contracts_pass(con: duckdb.DuckDBPyConnection) -> None:
    results = run_all(con)
    blocks = [r for r in results if r.severity == Severity.BLOCK and not r.passed]
    if blocks:
        raise QualityFailure(blocks)
