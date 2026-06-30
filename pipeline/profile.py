"""Challenge 9 — The Swarm. Parallel source profiling -> a single "swamp health" view.

Two ways to run the same scoring:

  1. Deterministic coordinator (this module): `python -m pipeline.profile` profiles all
     seven sources and writes build/swamp_health.json + a printed dashboard. Reproducible,
     runs in CI, no API calls.

  2. Agentic swarm: a Claude coordinator dispatches ONE Task subagent per source, each
     given ONLY the context in SUBAGENT_PROMPT (subagents don't inherit coordinator
     context — so it's passed explicitly), each emitting the SAME structured report this
     module produces. The coordinator aggregates identically. See docs/swarm.md for the
     exact prompts each subagent received — that legibility is part of the artifact.

Per-source score dimensions (0..1, higher = healthier):
  completeness, freshness, key_coverage, anomaly (inverse), pii_surface (inverse).
"""
from __future__ import annotations

import datetime as dt
import json

from . import common
from .contracts import SOURCE_CONTRACTS

# The exact context handed to each Task subagent. No coordinator state is assumed.
SUBAGENT_PROMPT = """\
You are profiling ONE source system in the Fabrikam Customer-360 swamp. Context you need
(you do NOT inherit anything else):

  source        = {source}
  raw table     = raw_customer (filter source_system = '{source}')
  contract      = {contract}
  warehouse     = warehouse.duckdb (DuckDB, read-only)

Score these 0..1 (1 = healthy) and return STRICT JSON with keys
{{completeness, freshness, key_coverage, anomaly_count, pii_surface, notes}}:
  - completeness : share of non-empty values across the contract's identity fields
  - freshness    : how recent the newest record is (decay over 24 months)
  - key_coverage : share of rows with a usable natural key
  - anomaly_count: integer count of obviously bad rows (sentinels, empty, � encoding)
  - pii_surface  : how many PII field types are present unmasked (email/phone/dob/address)
  - notes        : one sentence an analyst would care about
Do not invent rows. Read only raw_customer for your source.
"""


def _rows(con, source):
    return [json.loads(r[0]) for r in con.execute(
        "SELECT raw_payload FROM raw_customer WHERE source_system=?", [source]).fetchall()]


def profile_source(con, source: str) -> dict:
    c = SOURCE_CONTRACTS[source]
    rows = _rows(con, source)
    n = len(rows) or 1
    cols = c["columns"]

    # completeness over the identity-bearing fields
    filled = sum(1 for r in rows for k in cols if str(r.get(k, "")).strip()
                 not in ("", "NULL", "N/A", "null"))
    completeness = round(filled / (n * len(cols)), 3)

    # key coverage
    keyed = sum(1 for r in rows if str(r.get(c["key"], "")).strip())
    key_coverage = round(keyed / n, 3)

    # anomalies: empty/sentinel/encoding-loss rows
    anomalies = 0
    for r in rows:
        blob = json.dumps(r, ensure_ascii=False)
        if "�" in blob or "TEST" in blob.upper() or "999999" in blob or not any(
                str(v).strip() for v in r.values()):
            anomalies += 1

    # freshness from any conformed timestamp for this source
    newest = con.execute(
        "SELECT max(created_at_utc) FROM conformed_customer WHERE source_system=?",
        [source]).fetchone()[0]
    if newest:
        months = (dt.datetime.now(dt.timezone.utc) - newest).days / 30.0
        freshness = round(max(0.0, 1.0 - months / 60.0), 3)  # decay over 5y; this data is old
    else:
        freshness = 0.0

    # PII surface: which sensitive field types appear
    text = " ".join(cols).lower()
    pii_types = sum(t in text or any(t in k.lower() for k in cols)
                    for t in ["email", "phone", "tel", "birth", "dob", "geburt",
                              "addr", "street", "strasse"])
    pii_surface = round(min(pii_types, 5) / 5.0, 3)

    health = round((completeness + freshness + key_coverage
                    + (1 - min(anomalies / n, 1))) / 4.0, 3)
    return {
        "source": source, "rows": len(rows),
        "completeness": completeness, "freshness": freshness,
        "key_coverage": key_coverage, "anomaly_count": anomalies,
        "pii_surface": pii_surface, "health": health,
        "notes": c["notes"].split(".")[0] + ".",
    }


def run(con) -> dict:
    reports = [profile_source(con, s) for s in SOURCE_CONTRACTS]
    reports.sort(key=lambda r: r["health"])
    dashboard = {
        "generated_for": "swamp health",
        "sources": reports,
        "swamp_health": round(sum(r["health"] for r in reports) / len(reports), 3),
        "total_rows": sum(r["rows"] for r in reports),
        "total_anomalies": sum(r["anomaly_count"] for r in reports),
        "worst_source": reports[0]["source"],
    }
    out = common.ROOT / "build"
    out.mkdir(exist_ok=True)
    (out / "swamp_health.json").write_text(json.dumps(dashboard, indent=2))
    return dashboard


def _print(d: dict):
    print(f"\n  SWAMP HEALTH: {d['swamp_health']:.2f}   "
          f"({d['total_rows']} rows, {d['total_anomalies']} anomalies)\n")
    print(f"  {'source':<16}{'rows':>5}{'compl':>8}{'fresh':>8}{'keys':>7}"
          f"{'anom':>6}{'pii':>6}{'health':>8}")
    print("  " + "-" * 64)
    for r in d["sources"]:
        bar = "█" * int(r["health"] * 10)
        print(f"  {r['source']:<16}{r['rows']:>5}{r['completeness']:>8.2f}"
              f"{r['freshness']:>8.2f}{r['key_coverage']:>7.2f}{r['anomaly_count']:>6}"
              f"{r['pii_surface']:>6.2f}{r['health']:>8.2f}  {bar}")


if __name__ == "__main__":
    with common.connect(read_only=True) as con:
        _print(run(con))
