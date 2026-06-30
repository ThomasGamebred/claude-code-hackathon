"""Challenge 3 — The Intake. Land every source in the RAW zone, verbatim, with lineage.

Raw zone rules (see zones/raw/CLAUDE.md):
  - Store exactly what the source emitted. No cleaning, no type coercion.
  - Every row carries lineage: source_system, source_record_id, file path,
    ingest order, and a stable lineage_id you can trace back to.
  - Immutable & append-only in spirit; here we replace per-run for reproducibility.

Three deliberately different intake shapes, as the challenge asks for:
  - batch file  : the CSV/pipe sources (pos, crm, rheinland, sunset, northwind)
  - nested API  : ecommerce JSON (simulates a paginated API payload)
  - "CDC stream": loyalty is read row-by-row as if tailing a change feed

The parse-validate-RETRY loop lives in conform.py — raw landing must never reject a
row (you can't fix what you didn't keep), so raw takes everything and flags nothing.
"""
from __future__ import annotations

import csv
import io
import json

from . import common
from .contracts import SOURCE_CONTRACTS

RAW_DDL = """
CREATE OR REPLACE TABLE raw_customer (
    lineage_id        VARCHAR,
    source_system     VARCHAR,
    source_record_id  VARCHAR,
    ingest_seq        BIGINT,
    source_file       VARCHAR,
    raw_payload       JSON
);
"""


def _read_text(path, encoding: str) -> str:
    # errors='replace' so a bad byte never aborts the whole load; the � it leaves
    # behind is itself a signal the DQ layer will catch.
    return (common.SOURCES / path).read_text(encoding=encoding, errors="replace")


def _rows_csv(text: str, delimiter: str) -> list[dict]:
    # csv handles embedded newlines inside quoted fields (Sunset needs this).
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter, restkey="_overflow")
    out = []
    for r in reader:
        # ragged rows (Sunset's embedded commas) give DictReader a None key holding
        # the overflow list; stringify keys and JSON-safe the overflow.
        clean = {}
        for k, v in r.items():
            key = "_overflow" if k is None else str(k)
            clean[key] = v if not isinstance(v, list) else ", ".join(str(x) for x in v)
        out.append(clean)
    return out


def _rows_json(text: str) -> list[dict]:
    payload = json.loads(text)
    return payload if isinstance(payload, list) else payload.get("data", [])


def load_source(con, name: str) -> int:
    c = SOURCE_CONTRACTS[name]
    text = _read_text(c["path"], c["encoding"])
    if c["format"] in ("csv", "pipe"):
        rows = _rows_csv(text, c["delimiter"])
    else:
        rows = _rows_json(text)

    inserted = 0
    for seq, row in enumerate(rows):
        # an all-empty row (Sunset SC1099 territory) has no usable key — keep it,
        # but synthesize a key so lineage still resolves.
        key = str(row.get(c["key"]) or "").strip() or f"_emptyrow_{seq}"
        payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
        lid = common.row_lineage_id(name, key, payload)
        con.execute(
            "INSERT INTO raw_customer VALUES (?, ?, ?, ?, ?, ?)",
            [lid, name, key, seq, c["path"], payload],
        )
        inserted += 1
    return inserted


def run(con) -> dict[str, int]:
    con.execute(RAW_DDL)
    counts = {name: load_source(con, name) for name in SOURCE_CONTRACTS}
    total = con.execute("SELECT count(*) FROM raw_customer").fetchone()[0]
    counts["_total"] = total
    return counts


if __name__ == "__main__":
    with common.connect() as con:
        print(json.dumps(run(con), indent=2))
