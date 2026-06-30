#!/usr/bin/env python
"""Challenge 8 — The Trace. An MCP server over the Customer-360 lakehouse.

Four small, sharp tools so a fresh Claude session picks the right one on the first try:
    preview_table       — see what a table looks like before querying it
    trace_lineage       — walk a golden record back to its source rows + transformations
    find_record         — locate a customer by name / email / phone across the zones
    get_source_schema    — the producer contract for one source system

Design notes (Tool Design domain):
  - Each description says what the tool DOES and what it does NOT do, with input
    formats and example queries — that's what makes selection reliable.
  - Errors are STRUCTURED: {"isError": true, "code": ..., "guidance": ...} so the agent
    can recover instead of guessing.
  - Tool count is deliberately small (4). Reliability drops past a handful.

Run: `make mcp` (stdio). Register in Claude Code with:
  claude mcp add customer360 -- .venv/bin/python mcp/server.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import common  # noqa: E402
from pipeline.contracts import SOURCE_CONTRACTS  # noqa: E402

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    sys.stderr.write("mcp package not installed. Run: .venv/bin/pip install mcp\n")
    raise

mcp = FastMCP("customer360")

ALLOWED_TABLES = {"raw_customer", "conformed_customer", "curated_customer",
                  "conform_log", "match_review_queue"}


def _err(code: str, guidance: str, **extra) -> str:
    return json.dumps({"isError": True, "code": code, "guidance": guidance, **extra})


def _con():
    return common.connect(read_only=True)


@mcp.tool()
def preview_table(table: str, limit: int = 5) -> str:
    """Return a small sample of rows from one warehouse table, to see its shape and
    real values before you write a query.

    Input: `table` must be one of: raw_customer, conformed_customer, curated_customer,
    conform_log, match_review_queue. `limit` is capped at 50.

    Does NOT: run arbitrary SQL, join tables, or filter (use find_record to search,
    trace_lineage to follow links). Returns JSON {columns, rows}.
    Example: preview_table(table="curated_customer", limit=3)."""
    if table not in ALLOWED_TABLES:
        return _err("UNKNOWN_TABLE", f"Pick one of {sorted(ALLOWED_TABLES)}.", got=table)
    limit = max(1, min(int(limit), 50))
    with _con() as con:
        if table not in {r[0] for r in con.execute("SHOW TABLES").fetchall()}:
            return _err("NOT_BUILT", "Warehouse table missing — run `make build` first.", table=table)
        cur = con.execute(f"SELECT * FROM {table} LIMIT {limit}")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return json.dumps({"table": table, "columns": cols, "rows": rows}, default=str)


@mcp.tool()
def trace_lineage(golden_id: str) -> str:
    """Walk a CURATED golden record back to every source row that fed it, including the
    per-field transformations applied (encoding repair, date/format normalization).

    Use this to answer "where did this value in the report come from?". Input: a
    `golden_id` like 'G-abc123...' (from curated_customer.golden_id or find_record).

    Does NOT: trace conformed/raw ids directly (pass a golden_id), and does NOT modify
    anything. Returns JSON {golden_id, golden, members:[{source, raw, conformed_flags}]}.
    Example: trace_lineage(golden_id="G-1a2b3c...")."""
    with _con() as con:
        g = con.execute("SELECT * FROM curated_customer WHERE golden_id=?", [golden_id]).fetchone()
        if not g:
            return _err("NOT_FOUND", "No such golden_id. Use find_record to locate one.",
                        golden_id=golden_id)
        gcols = [d[0] for d in con.description]
        golden = dict(zip(gcols, g))
        member_ids = json.loads(golden["member_lineage_ids"])
        members = []
        for lid in member_ids:
            raw = con.execute(
                "SELECT source_system, source_record_id, source_file, raw_payload "
                "FROM raw_customer WHERE lineage_id=?", [lid]).fetchone()
            flags = con.execute(
                "SELECT dq_flags FROM conformed_customer WHERE lineage_id=?", [lid]).fetchone()
            members.append({
                "lineage_id": lid,
                "source_system": raw[0] if raw else None,
                "source_record_id": raw[1] if raw else None,
                "source_file": raw[2] if raw else None,
                "raw_payload": json.loads(raw[3]) if raw else None,
                "conform_flags": (flags[0] if flags else None),
            })
    return json.dumps({
        "golden_id": golden_id,
        "golden": {k: golden[k] for k in ("full_name", "email", "phone", "match_confidence")},
        "field_provenance": json.loads(golden["field_provenance"]),
        "field_confidence": json.loads(golden["field_confidence"]),
        "members": members,
    }, default=str)


@mcp.tool()
def find_record(query: str, zone: str = "curated") -> str:
    """Find customers matching a free-text `query` (a name fragment, an email, or a
    phone) so you can get a golden_id or lineage_id to trace.

    Input: `query` is matched case-insensitively against name/email/phone. `zone` is
    'curated' (golden records, default) or 'conformed' (per-source rows).

    Does NOT: do fuzzy entity matching (that's the pipeline's job) — it's a substring
    lookup. Returns JSON {matches:[...]} (max 20). Example: find_record(query="hernandez").
    Returns a structured error if `query` is shorter than 2 characters."""
    q = (query or "").strip()
    if len(q) < 2:
        return _err("QUERY_TOO_SHORT", "Give at least 2 characters.", query=query)
    if zone not in ("curated", "conformed"):
        return _err("BAD_ZONE", "zone must be 'curated' or 'conformed'.", got=zone)
    like = f"%{q.lower()}%"
    with _con() as con:
        if zone == "curated":
            rows = con.execute(
                "SELECT golden_id, full_name, email, phone, member_sources, match_confidence "
                "FROM curated_customer WHERE lower(full_name) LIKE ? OR lower(email) LIKE ? "
                "OR phone LIKE ? LIMIT 20", [like, like, like]).fetchall()
            keys = ["golden_id", "full_name", "email", "phone", "member_sources", "match_confidence"]
        else:
            rows = con.execute(
                "SELECT lineage_id, source_system, full_name, email, phone "
                "FROM conformed_customer WHERE lower(full_name) LIKE ? OR lower(email) LIKE ? "
                "OR phone LIKE ? LIMIT 20", [like, like, like]).fetchall()
            keys = ["lineage_id", "source_system", "full_name", "email", "phone"]
        matches = [dict(zip(keys, r)) for r in rows]
    if not matches:
        return _err("NO_MATCHES", "Nothing matched. Try a shorter or different fragment.", query=q)
    return json.dumps({"zone": zone, "query": q, "matches": matches}, default=str)


@mcp.tool()
def get_source_schema(source: str) -> str:
    """Return the producer CONTRACT for one source system: its columns, key, delimiter,
    encoding, assumed timezone, and known quirks.

    Use this to understand what a source actually promises before reading its raw rows.
    Input: `source` is one of pos, ecommerce, loyalty, crm, acq_rheinland, acq_sunset,
    acq_northwind. Does NOT return data rows (use preview_table) — it returns the schema only.
    Example: get_source_schema(source="loyalty")."""
    if source not in SOURCE_CONTRACTS:
        return _err("UNKNOWN_SOURCE", f"Pick one of {sorted(SOURCE_CONTRACTS)}.", got=source)
    c = SOURCE_CONTRACTS[source]
    return json.dumps({
        "source": source, "key": c["key"], "format": c["format"],
        "delimiter": c.get("delimiter"), "encoding": c["encoding"],
        "assumed_timezone": c["tz"], "columns": c["columns"], "quirks": c["notes"],
    })


if __name__ == "__main__":
    mcp.run()
