"""Stdio MCP server exposing trace + preview tools over the Fabrikam lakehouse.

Design notes
------------

The tool surface is intentionally **six tools, no SQL passthrough**:

* ``list_sources`` — orient ("which sources exist?")
* ``preview_table`` — narrow read of a single named table
* ``find_record`` — fuzzy-by-text search across the conformed customer view
* ``trace_lineage`` — given a curated ``customer_id``, walk back to raw rows
* ``get_source_schema`` — read the canonical column list before changing conform
* ``quality_status`` — is the curated zone currently green?

Each tool description includes input format, edge cases, and an explicit
"this tool does NOT do X" line, because a fresh Claude session typically picks
the wrong tool when descriptions are vague about boundaries.

The DuckDB connection is opened **read-only** and only when the warehouse file
exists; if the file is missing (e.g. the pipeline has not been run), every tool
returns a structured error with ``reason_code = "WAREHOUSE_MISSING"``.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import duckdb
from pydantic import BaseModel, Field, ValidationError

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


# ---------------------------------------------------------------------------
# Constants / catalog
# ---------------------------------------------------------------------------

SEVEN_SOURCES: tuple[str, ...] = (
    "acq_northwind",
    "acq_rheinland",
    "acq_sunset",
    "crm",
    "ecommerce",
    "loyalty",
    "pos",
)

#: Tables the agent is allowed to ``preview_table`` against. Allow-listed so a
#: typo cannot accidentally hit, say, ``information_schema`` or a temp table.
ALLOWED_TABLES: frozenset[str] = frozenset(
    {f"raw.{s}" for s in SEVEN_SOURCES}
    | {
        "conformed.customer",
        "conformed._reject",
        "curated.customer_master",
        "curated.customer_xref",
        "curated.match_audit",
        "curated.customer_review",
    }
)

#: Per-source canonical column list + known issues. Kept in code (not the DB)
#: so ``get_source_schema`` works even before the pipeline has run.
SOURCE_CATALOG: dict[str, dict[str, Any]] = {
    "acq_northwind": {
        "source_file": "acq_northwind/legacy_customers.txt",
        "delimiter": "|",
        "encoding": "utf-8",
        "columns": [
            "CUSTNO", "CUSTNAME", "ADDR1", "CITY", "ST", "ZIP",
            "PHONE", "DTADDED", "DTBIRTH", "STATUS",
        ],
        "known_issues": [
            "Pipe-delimited legacy export; CUSTNAME is `LAST, FIRST` with stray whitespace.",
            "DTADDED / DTBIRTH are MM/DD/YY two-digit years; ambiguous beyond 2049.",
            "STATUS uses single-letter codes ('A','I','D') that the conform layer must expand.",
        ],
    },
    "acq_rheinland": {
        "source_file": "acq_rheinland/kunden.csv",
        "delimiter": ";",
        "encoding": "mixed (cp1252 fragments inside utf-8)",
        "columns": [
            "Kundennr", "Name", "Strasse", "PLZ", "Ort", "Telefon",
            "Email", "Geburtsdatum", "Umsatz", "Newsletter",
        ],
        "known_issues": [
            "Mojibake on umlauts; ingest sets `_encoding_fixed` when a row needed cp1252 decode.",
            "Geburtsdatum is `DD.MM.YYYY` (European).",
            "Telefon may carry a German national format without country code.",
        ],
    },
    "acq_sunset": {
        "source_file": "acq_sunset/catalog_customers.csv",
        "delimiter": ",",
        "encoding": "utf-8-lossy",
        "columns": [
            "acct", "name", "address", "city", "st", "zip",
            "phone", "signup_dt", "email", "notes",
        ],
        "known_issues": [
            "signup_dt is an Excel serial date number (days since 1899-12-30).",
            "`notes` contains embedded newlines that must be quoted to parse correctly.",
            "`name` is occasionally truncated mid-word at column 40.",
        ],
    },
    "crm": {
        "source_file": "crm/crm_contacts.csv",
        "delimiter": ",",
        "encoding": "utf-8-sig (BOM)",
        "columns": [
            "contact_id", "account_name", "full_name", "email", "phone",
            "mailing_street", "mailing_city", "mailing_state", "mailing_zip",
            "date_of_birth", "lead_source", "created_date",
        ],
        "known_issues": [
            "Literal string 'NULL' is used instead of empty for missing values.",
            "date_of_birth carries 2-digit years; created_date carries 4-digit years.",
            "BOM on first column header; ingest must strip.",
        ],
    },
    "ecommerce": {
        "source_file": "ecommerce/customers.json",
        "delimiter": None,
        "encoding": "utf-8",
        "columns": [
            "customer_id", "first_name", "last_name", "email", "phone",
            "created_at", "line1", "city", "region", "postal_code", "country",
            "marketing_opt_in", "total_orders",
        ],
        "known_issues": [
            "`created_at` is ISO-8601 with an explicit offset; survives as UTC after conform.",
            "Considered the most trustworthy source for email and birth_date in survivorship.",
        ],
    },
    "loyalty": {
        "source_file": "loyalty/loyalty_members.csv",
        "delimiter": ",",
        "encoding": "utf-8",
        "columns": [
            "member_id", "full_name", "email", "phone", "tier", "points_balance",
            "enrolled_at", "birth_date", "home_store", "pos_customer_id",
        ],
        "known_issues": [
            "`pos_customer_id` is a soft FK to `pos.CUST_ID`; ~6% of references dangle.",
            "Authoritative source for `birth_date` after ecommerce.",
        ],
    },
    "pos": {
        "source_file": "pos/pos_export_2023-11.csv",
        "delimiter": ",",
        "encoding": "utf-8-lossy",
        "columns": [
            "CUST_ID", "NAME", "PHONE", "EMAIL", "ADDR", "CITY", "STATE",
            "ZIP", "DOB", "LAST_TXN_DATE", "LIFETIME_SPEND",
        ],
        "known_issues": [
            "ZIPs frequently truncated to 4 digits (leading zero stripped).",
            "Same NAME can appear multiple times with different CUST_ID — true duplicates.",
            "PHONE rarely normalized; expect parens, dashes, extensions.",
        ],
    },
}


# ---------------------------------------------------------------------------
# Warehouse handle
# ---------------------------------------------------------------------------


def _warehouse_path() -> Path:
    """Resolve the DuckDB file path.

    Honors ``FABRIKAM_WAREHOUSE`` for tests / non-standard layouts; otherwise
    points at the repo's ``warehouse/fabrikam.duckdb``.
    """
    override = os.environ.get("FABRIKAM_WAREHOUSE")
    if override:
        return Path(override)
    # mcp/fabrikam_mcp/server.py -> repo root is parents[2]
    return Path(__file__).resolve().parents[2] / "warehouse" / "fabrikam.duckdb"


@dataclass
class Warehouse:
    """Lazy read-only DuckDB connection."""

    path: Path
    _conn: duckdb.DuckDBPyConnection | None = None

    def available(self) -> bool:
        return self.path.exists()

    def connect(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            # ``read_only=True`` is the load-bearing piece: this server must never
            # mutate the warehouse, no matter what an agent asks for.
            self._conn = duckdb.connect(str(self.path), read_only=True)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# ---------------------------------------------------------------------------
# Helpers — structured errors + result envelopes
# ---------------------------------------------------------------------------


def _err(reason_code: str, message: str, **extra: Any) -> dict[str, Any]:
    """Build a structured error envelope.

    The MCP spec lets a tool return ``isError: true`` alongside content; we put
    a JSON body in ``content`` so an agent can read ``reason_code`` directly.
    """
    body = {"isError": True, "reason_code": reason_code, "message": message, **extra}
    return body


def _ok(payload: Any) -> dict[str, Any]:
    return {"isError": False, "data": payload}


def _as_tool_response(body: dict[str, Any]) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(body, default=str, indent=2))]


def _rows_to_dicts(cur: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    cols = [d[0] for d in cur.description] if cur.description else []
    return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# WHERE-clause sanitizer for preview_table
# ---------------------------------------------------------------------------

# Forbidden tokens in a where clause. We do not try to build a full SQL parser;
# instead we apply a coarse, deny-list filter. The fact that the connection is
# read-only is the real defense — this is belt-and-braces.
_FORBIDDEN_WHERE = re.compile(
    r"(?i)\b(insert|update|delete|drop|alter|attach|copy|pragma|create|"
    r"replace|grant|revoke|truncate|vacuum|export)\b|;|--|/\*|\*/"
)


def _sanitize_where(where: str) -> tuple[bool, str]:
    if _FORBIDDEN_WHERE.search(where):
        return False, "WHERE clause contains a forbidden keyword or comment."
    if len(where) > 500:
        return False, "WHERE clause exceeds 500 characters."
    return True, ""


# ---------------------------------------------------------------------------
# Pydantic input models
# ---------------------------------------------------------------------------


class ListSourcesInput(BaseModel):
    """No arguments."""


class PreviewTableInput(BaseModel):
    table: str = Field(
        ...,
        description=(
            "Fully-qualified table name, e.g. 'raw.crm', 'conformed.customer', "
            "'curated.customer_master'. Must be on the allow-list."
        ),
    )
    limit: int = Field(
        10,
        ge=1,
        le=200,
        description="Row cap (1..200). Default 10.",
    )
    where: str | None = Field(
        None,
        description=(
            "Optional SQL WHERE body WITHOUT the WHERE keyword and WITHOUT a "
            "trailing semicolon, e.g. \"email_normalized = 'a@b.com'\" or "
            "\"_source = 'crm' AND city = 'Köln'\". DDL/DML keywords are rejected."
        ),
    )


class FindRecordInput(BaseModel):
    query: str = Field(
        ...,
        min_length=2,
        description=(
            "Free-text fragment to search for — a name, an email, a phone "
            "substring, a city. Matched case-insensitively against "
            "first_name, last_name, full_name_normalized, email_normalized, "
            "phone_e164 in conformed.customer."
        ),
    )
    source: str | None = Field(
        None,
        description=(
            "Optional source filter; one of: "
            "acq_northwind, acq_rheinland, acq_sunset, crm, ecommerce, loyalty, pos."
        ),
    )
    limit: int = Field(20, ge=1, le=100)


class TraceLineageInput(BaseModel):
    customer_id: str = Field(
        ...,
        description="Curated customer_id (uuid string) from curated.customer_master.",
    )


class GetSourceSchemaInput(BaseModel):
    source: str = Field(
        ...,
        description=(
            "Source name; one of: acq_northwind, acq_rheinland, acq_sunset, "
            "crm, ecommerce, loyalty, pos."
        ),
    )


class QualityStatusInput(BaseModel):
    """No arguments."""


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _require_warehouse(wh: Warehouse) -> dict[str, Any] | None:
    if not wh.available():
        return _err(
            "WAREHOUSE_MISSING",
            (
                "The DuckDB warehouse file does not exist yet. "
                "Run `make pipeline` from the repo root (or set FABRIKAM_WAREHOUSE) "
                "and try again."
            ),
            expected_path=str(wh.path),
        )
    return None


def tool_list_sources(wh: Warehouse, _: ListSourcesInput) -> dict[str, Any]:
    miss = _require_warehouse(wh)
    if miss:
        return miss
    conn = wh.connect()
    out = []
    for name in SEVEN_SOURCES:
        try:
            (cnt,) = conn.execute(f"SELECT COUNT(*) FROM raw.{name}").fetchone()
        except duckdb.Error as exc:
            out.append({"source": name, "row_count": None, "error": str(exc)})
            continue
        out.append(
            {
                "source": name,
                "row_count": cnt,
                "source_file": SOURCE_CATALOG[name]["source_file"],
            }
        )
    return _ok(out)


def tool_preview_table(wh: Warehouse, args: PreviewTableInput) -> dict[str, Any]:
    miss = _require_warehouse(wh)
    if miss:
        return miss
    table = args.table.strip()
    if table not in ALLOWED_TABLES:
        return _err(
            "TABLE_NOT_FOUND",
            f"Table '{table}' is not on the allow-list.",
            allowed=sorted(ALLOWED_TABLES),
        )
    sql = f"SELECT * FROM {table}"
    if args.where:
        ok, why = _sanitize_where(args.where)
        if not ok:
            return _err("BAD_WHERE", why)
        sql += f" WHERE {args.where}"
    sql += f" LIMIT {int(args.limit)}"
    try:
        cur = wh.connect().execute(sql)
    except duckdb.Error as exc:
        return _err("QUERY_FAILED", str(exc), sql=sql)
    rows = _rows_to_dicts(cur)
    return _ok({"table": table, "row_count": len(rows), "rows": rows, "sql": sql})


def tool_find_record(wh: Warehouse, args: FindRecordInput) -> dict[str, Any]:
    miss = _require_warehouse(wh)
    if miss:
        return miss
    if args.source is not None and args.source not in SEVEN_SOURCES:
        return _err(
            "UNKNOWN_SOURCE",
            f"Unknown source '{args.source}'.",
            known=list(SEVEN_SOURCES),
        )

    needle = f"%{args.query.lower()}%"
    params: list[Any] = []
    where_parts = [
        "("
        "LOWER(COALESCE(full_name_normalized,'')) LIKE ?"
        " OR LOWER(COALESCE(first_name,'')) LIKE ?"
        " OR LOWER(COALESCE(last_name,'')) LIKE ?"
        " OR LOWER(COALESCE(email_normalized,'')) LIKE ?"
        " OR LOWER(COALESCE(phone_e164,'')) LIKE ?"
        ")"
    ]
    params.extend([needle] * 5)
    if args.source:
        where_parts.append("_source = ?")
        params.append(args.source)
    sql = (
        "SELECT _source, _source_id, _source_row, first_name, last_name, "
        "full_name_normalized, email_normalized, phone_e164, city, region, country, "
        "birth_date "
        "FROM conformed.customer WHERE "
        + " AND ".join(where_parts)
        + " LIMIT ?"
    )
    params.append(int(args.limit))
    try:
        cur = wh.connect().execute(sql, params)
    except duckdb.Error as exc:
        return _err("QUERY_FAILED", str(exc))
    rows = _rows_to_dicts(cur)
    if not rows:
        return _err(
            "NO_MATCH",
            f"No conformed.customer rows match '{args.query}'.",
            hint=(
                "Try a shorter substring, drop the source filter, or use "
                "preview_table on the raw zone if the row may have failed conform."
            ),
        )
    return _ok(
        {
            "query": args.query,
            "source_filter": args.source,
            "row_count": len(rows),
            "rows": rows,
            "next_step": (
                "Pick a candidate and call trace_lineage(customer_id=...) "
                "after resolving its curated id via curated.customer_xref."
            ),
        }
    )


def tool_trace_lineage(wh: Warehouse, args: TraceLineageInput) -> dict[str, Any]:
    miss = _require_warehouse(wh)
    if miss:
        return miss
    conn = wh.connect()
    customer_id = args.customer_id.strip()

    master_rows = _rows_to_dicts(
        conn.execute(
            "SELECT * FROM curated.customer_master WHERE customer_id = ?",
            [customer_id],
        )
    )
    if not master_rows:
        return _err(
            "NO_MATCH",
            f"No curated.customer_master row with customer_id = '{customer_id}'.",
            hint="Use find_record() to discover the customer_id from a name/email.",
        )
    master = master_rows[0]

    xrefs = _rows_to_dicts(
        conn.execute(
            "SELECT _source, _source_id, match_method, match_score "
            "FROM curated.customer_xref WHERE customer_id = ? "
            "ORDER BY _source, _source_id",
            [customer_id],
        )
    )

    tree: dict[str, Any] = {
        "level": "curated",
        "table": "curated.customer_master",
        "primary_key": {"customer_id": customer_id},
        "record_confidence": master.get("record_confidence"),
        "n_sources": master.get("n_sources"),
        "row": master,
        "children": [],
    }

    for x in xrefs:
        conformed_rows = _rows_to_dicts(
            conn.execute(
                "SELECT * FROM conformed.customer "
                "WHERE _source = ? AND _source_id = ?",
                [x["_source"], x["_source_id"]],
            )
        )
        conformed_row = conformed_rows[0] if conformed_rows else None
        source = x["_source"]
        raw_row = None
        if conformed_row is not None and source in SEVEN_SOURCES:
            try:
                raw_rows = _rows_to_dicts(
                    conn.execute(
                        f"SELECT * FROM raw.{source} "
                        "WHERE _source_row = ? AND _source = ?",
                        [conformed_row.get("_source_row"), source],
                    )
                )
                if raw_rows:
                    raw_row = raw_rows[0]
            except duckdb.Error:
                raw_row = None

        tree["children"].append(
            {
                "level": "conformed",
                "table": "conformed.customer",
                "match_method": x.get("match_method"),
                "match_score": x.get("match_score"),
                "primary_key": {
                    "_source": x["_source"],
                    "_source_id": x["_source_id"],
                },
                "row": conformed_row,
                "children": [
                    {
                        "level": "raw",
                        "table": f"raw.{source}",
                        "lineage": {
                            "_source": (raw_row or {}).get("_source"),
                            "_source_file": (raw_row or {}).get("_source_file"),
                            "_source_row": (raw_row or {}).get("_source_row"),
                            "_ingested_at": (raw_row or {}).get("_ingested_at"),
                        },
                        "row": raw_row,
                        "children": [],
                    }
                ],
            }
        )

    audit = _rows_to_dicts(
        conn.execute(
            "SELECT audit_id, event_type, decision, score, note, created_at "
            "FROM curated.match_audit WHERE customer_id = ? "
            "ORDER BY created_at",
            [customer_id],
        )
    )

    return _ok({"trace": tree, "match_audit": audit})


def tool_get_source_schema(wh: Warehouse, args: GetSourceSchemaInput) -> dict[str, Any]:
    # This tool intentionally works without the warehouse — the catalog lives
    # in code, so an engineer can plan a conform change before pipeline runs.
    if args.source not in SOURCE_CATALOG:
        return _err(
            "UNKNOWN_SOURCE",
            f"Unknown source '{args.source}'.",
            known=list(SOURCE_CATALOG),
        )
    cat = SOURCE_CATALOG[args.source]
    return _ok(
        {
            "source": args.source,
            "source_file": cat["source_file"],
            "delimiter": cat["delimiter"],
            "encoding": cat["encoding"],
            "columns": cat["columns"],
            "known_issues": cat["known_issues"],
            "lineage_columns": [
                "_source",
                "_source_file",
                "_source_row",
                "_ingested_at",
                "_raw_payload",
            ],
            "warehouse_table": f"raw.{args.source}",
        }
    )


def tool_quality_status(wh: Warehouse, _: QualityStatusInput) -> dict[str, Any]:
    miss = _require_warehouse(wh)
    if miss:
        return miss
    conn = wh.connect()

    # Try a dedicated quality table first (if the backend persists one); fall
    # back to derived signals so the tool is still useful when it doesn't.
    checks: list[dict[str, Any]] = []
    overall = "GREEN"

    try:
        rows = _rows_to_dicts(
            conn.execute(
                "SELECT check_name, severity, status, detail, checked_at "
                "FROM curated.quality_status ORDER BY checked_at DESC"
            )
        )
        for r in rows:
            checks.append(r)
            if r.get("severity") == "BLOCK" and r.get("status") != "PASS":
                overall = "BLOCKED"
            elif overall == "GREEN" and r.get("status") != "PASS":
                overall = "ALERT"
        if rows:
            return _ok(
                {"overall": overall, "source": "curated.quality_status", "checks": checks}
            )
    except duckdb.Error:
        pass  # Table doesn't exist yet — derive instead.

    # Derived fallback.
    try:
        (n_master,) = conn.execute(
            "SELECT COUNT(*) FROM curated.customer_master"
        ).fetchone()
    except duckdb.Error:
        n_master = 0
    try:
        (n_reject,) = conn.execute("SELECT COUNT(*) FROM conformed._reject").fetchone()
    except duckdb.Error:
        n_reject = 0
    try:
        (n_review,) = conn.execute(
            "SELECT COUNT(*) FROM curated.customer_review"
        ).fetchone()
    except duckdb.Error:
        n_review = 0

    checks = [
        {
            "check_name": "curated_master_populated",
            "severity": "BLOCK",
            "status": "PASS" if n_master > 0 else "FAIL",
            "detail": f"{n_master} rows in curated.customer_master",
        },
        {
            "check_name": "conform_reject_rate",
            "severity": "ALERT",
            "status": "PASS" if n_reject == 0 else "WARN",
            "detail": f"{n_reject} rows in conformed._reject",
        },
        {
            "check_name": "review_queue_depth",
            "severity": "INFO",
            "status": "PASS",
            "detail": f"{n_review} rows in curated.customer_review",
        },
    ]
    if any(c["status"] == "FAIL" and c["severity"] == "BLOCK" for c in checks):
        overall = "BLOCKED"
    elif any(c["status"] == "WARN" for c in checks):
        overall = "ALERT"
    return _ok(
        {
            "overall": overall,
            "source": "derived (curated.quality_status not present)",
            "checks": checks,
        }
    )


# ---------------------------------------------------------------------------
# Tool descriptions — the deliverable. Treat these as the contract.
# ---------------------------------------------------------------------------

TOOL_DESCRIPTIONS: dict[str, str] = {
    "list_sources": (
        "List the seven Fabrikam source systems and their current row counts in the raw zone. "
        "Use this when you don't yet know which sources contributed to a customer, or to "
        "sanity-check that ingestion ran (zero rows means the source didn't land).\n\n"
        "Returns: a list of objects with `source`, `row_count`, and `source_file` (path).\n"
        "Edge cases: returns reason_code=WAREHOUSE_MISSING if the DuckDB file isn't built yet "
        "(run `make pipeline`).\n"
        "Does NOT: list curated tables (use preview_table for that), describe source schemas "
        "(use get_source_schema), or count conformed/curated rows."
    ),
    "preview_table": (
        "Read-only preview of a single named table in the lakehouse, optionally filtered. "
        "Use this when you already know which table you want to look at and just need to see "
        "a few rows. Good for orienting after list_sources, or for inspecting "
        "conformed._reject after a quality failure.\n\n"
        "Inputs:\n"
        "  - table: fully-qualified table name. Allowed values:\n"
        "      raw.acq_northwind, raw.acq_rheinland, raw.acq_sunset, raw.crm,\n"
        "      raw.ecommerce, raw.loyalty, raw.pos,\n"
        "      conformed.customer, conformed._reject,\n"
        "      curated.customer_master, curated.customer_xref,\n"
        "      curated.match_audit, curated.customer_review.\n"
        "  - limit: 1..200 (default 10).\n"
        "  - where: optional SQL WHERE body WITHOUT the WHERE keyword and WITHOUT a trailing\n"
        "    semicolon. Example: \"email_normalized = 'a@b.com' AND _source = 'crm'\".\n"
        "    DDL/DML keywords (INSERT, UPDATE, DROP, ...), comments (--, /*), and ';' are\n"
        "    rejected with reason_code=BAD_WHERE.\n\n"
        "Edge cases: reason_code=TABLE_NOT_FOUND for unknown tables (full allow-list returned), "
        "WAREHOUSE_MISSING if the warehouse file doesn't exist.\n"
        "Does NOT: execute arbitrary SQL — this is SELECT * with an optional WHERE, nothing "
        "more. Does NOT mutate the warehouse (the DuckDB connection is opened read-only). "
        "If you need to JOIN across tables, use find_record or trace_lineage instead — those "
        "encode the joins you actually want."
    ),
    "find_record": (
        "Fuzzy text search across the conformed customer view. Use this when a user says "
        "'find John Smith' or 'who has the email j.doe@…' and you don't yet have a "
        "customer_id. Substring match (case-insensitive) against first_name, last_name, "
        "full_name_normalized, email_normalized, and phone_e164.\n\n"
        "Inputs:\n"
        "  - query: free-text fragment (a name, partial email, phone substring, etc.).\n"
        "           Minimum 2 characters.\n"
        "  - source: optional source filter — one of acq_northwind, acq_rheinland,\n"
        "           acq_sunset, crm, ecommerce, loyalty, pos.\n"
        "  - limit: 1..100 (default 20).\n\n"
        "Returns: a list of conformed rows, each carrying its `_source` and `_source_id`. "
        "Cardinality: one query can return many rows (one per source the person appears in).\n\n"
        "Edge cases: reason_code=NO_MATCH if nothing matches (with a hint suggesting a "
        "shorter substring or a check of the raw zone for failed-conform rows), "
        "UNKNOWN_SOURCE if `source` isn't one of the seven, WAREHOUSE_MISSING if the "
        "warehouse isn't built.\n"
        "Does NOT: return a curated customer_id directly — use the `_source`/`_source_id` to "
        "look up curated.customer_xref, then call trace_lineage(customer_id). Does NOT search "
        "raw rows (which may not have been conformed). Does NOT execute arbitrary SQL."
    ),
    "trace_lineage": (
        "Given a curated customer_id, walk all the way back to source rows. This is the "
        "entry point for 'given one bad value in a report, walk it back to the source row "
        "that produced it' — Challenge 8 (The Trace).\n\n"
        "Inputs:\n"
        "  - customer_id: the uuid string from curated.customer_master.\n\n"
        "Returns: a nested tree:\n"
        "  curated.customer_master\n"
        "    -> for each xref: conformed.customer row\n"
        "         -> raw.<source> row with its lineage metadata\n"
        "            (_source, _source_file, _source_row, _ingested_at).\n"
        "  Plus a `match_audit` list of decisions that produced this customer.\n\n"
        "Edge cases: reason_code=NO_MATCH if the customer_id doesn't exist in "
        "customer_master (with a hint to call find_record first); WAREHOUSE_MISSING if the "
        "warehouse isn't built.\n"
        "Does NOT: accept a name, email, phone, or source-side id — you must already have "
        "the curated customer_id (use find_record + curated.customer_xref to resolve it). "
        "Does NOT modify lineage or merge audit entries. Does NOT decrypt hashed PII in the "
        "curated row (email_hash / phone_hash stay hashed)."
    ),
    "get_source_schema": (
        "Return the canonical column list and known issues for one source. This is where to "
        "look BEFORE writing a conform-layer change — it tells you the on-disk shape, the "
        "delimiter, the encoding, and what dirt to expect.\n\n"
        "Inputs:\n"
        "  - source: one of acq_northwind, acq_rheinland, acq_sunset, crm, ecommerce,\n"
        "           loyalty, pos.\n\n"
        "Returns: source_file path, delimiter, encoding, ordered column list, known_issues "
        "(list of strings — encoding quirks, ambiguous date formats, soft FKs, etc.), the "
        "lineage columns appended at raw, and the corresponding raw.<source> table name.\n\n"
        "Edge cases: reason_code=UNKNOWN_SOURCE for typos (returns the full known list). "
        "This tool works EVEN IF the warehouse hasn't been built yet — the catalog lives in "
        "code so you can plan a conform change before the pipeline runs.\n"
        "Does NOT: return row counts (use list_sources), preview actual data (use "
        "preview_table on raw.<source>), or describe the conformed/curated schemas (those "
        "are stable; preview_table their tables to see column names)."
    ),
    "quality_status": (
        "Report the result of the last data-quality run as a structured list — tells you "
        "whether the curated zone is currently green, alerting, or blocked. Use this BEFORE "
        "drawing conclusions from curated.customer_master: if the overall status is BLOCKED, "
        "the curated rebuild was skipped and the numbers you see may be stale.\n\n"
        "Returns: { overall: 'GREEN' | 'ALERT' | 'BLOCKED', source: <where the status came "
        "from>, checks: [ { check_name, severity, status, detail, checked_at? } ] }.\n"
        "When curated.quality_status exists it is used verbatim; otherwise the tool derives "
        "a status from row counts in curated.customer_master, conformed._reject, and "
        "curated.customer_review (marked source='derived').\n\n"
        "Edge cases: reason_code=WAREHOUSE_MISSING if the warehouse file doesn't exist yet.\n"
        "Does NOT: re-run quality checks (it only reports the last result), modify the "
        "warehouse, or block writes — the PreToolUse hook in the backend does that."
    ),
}


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    model: type[BaseModel]
    handler: Any  # callable(Warehouse, model_instance) -> dict


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec("list_sources", TOOL_DESCRIPTIONS["list_sources"], ListSourcesInput, tool_list_sources),
    ToolSpec("preview_table", TOOL_DESCRIPTIONS["preview_table"], PreviewTableInput, tool_preview_table),
    ToolSpec("find_record", TOOL_DESCRIPTIONS["find_record"], FindRecordInput, tool_find_record),
    ToolSpec("trace_lineage", TOOL_DESCRIPTIONS["trace_lineage"], TraceLineageInput, tool_trace_lineage),
    ToolSpec("get_source_schema", TOOL_DESCRIPTIONS["get_source_schema"], GetSourceSchemaInput, tool_get_source_schema),
    ToolSpec("quality_status", TOOL_DESCRIPTIONS["quality_status"], QualityStatusInput, tool_quality_status),
)

TOOLS_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in TOOLS}


def call_tool(name: str, arguments: dict[str, Any] | None, wh: Warehouse) -> dict[str, Any]:
    """Synchronous tool dispatch. Exposed for tests."""
    spec = TOOLS_BY_NAME.get(name)
    if spec is None:
        return _err("UNKNOWN_TOOL", f"No tool named '{name}'.", known=list(TOOLS_BY_NAME))
    try:
        args = spec.model.model_validate(arguments or {})
    except ValidationError as exc:
        return _err("BAD_ARGUMENTS", "Input validation failed.", errors=exc.errors())
    try:
        return spec.handler(wh, args)
    except Exception as exc:  # pragma: no cover — last-ditch envelope
        return _err("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# MCP server wiring
# ---------------------------------------------------------------------------


def build_server(wh: Warehouse) -> Server:
    server: Server = Server("fabrikam-mcp")

    @server.list_tools()  # type: ignore[misc]
    async def _list_tools() -> list[Tool]:
        return [
            Tool(
                name=spec.name,
                description=spec.description,
                inputSchema=spec.model.model_json_schema(),
            )
            for spec in TOOLS
        ]

    @server.call_tool()  # type: ignore[misc]
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        body = call_tool(name, arguments, wh)
        return _as_tool_response(body)

    return server


async def _run_async() -> None:
    wh = Warehouse(path=_warehouse_path())
    try:
        server = build_server(wh)
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        wh.close()


def main() -> None:
    """Console-script entrypoint (``fabrikam-mcp``)."""
    asyncio.run(_run_async())


if __name__ == "__main__":  # pragma: no cover
    main()
