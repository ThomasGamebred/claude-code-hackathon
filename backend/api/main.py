"""FastAPI app backing the React frontend.

Endpoint shapes mirror frontend/src/api/types.ts. When the warehouse file
does not exist, every endpoint returns an empty payload (never 500).
"""
from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import duckdb
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from api.models import (
    CustomerDetail,
    CustomerSummary,
    FieldProvenance,
    LineageEdge,
    LineageGraph,
    LineageNode,
    QualityCheck,
    ReviewDecision,
    ReviewPair,
    ReviewSide,
    SourceContribution,
    SourceInfo,
)
from pipeline import quality
from pipeline.normalize import utc_now

REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent
DB_PATH: Path = REPO_ROOT / "warehouse" / "fabrikam.duckdb"
REPORT_PATH: Path = REPO_ROOT / "warehouse" / "last_run_report.json"

app = FastAPI(title="Fabrikam Single Customer View", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def warehouse_exists() -> bool:
    return DB_PATH.exists()


@contextmanager
def _con(read_only: bool = True) -> Iterator[duckdb.DuckDBPyConnection | None]:
    if not warehouse_exists():
        yield None
        return
    con = duckdb.connect(str(DB_PATH), read_only=read_only)
    try:
        yield con
    finally:
        con.close()


def _table_exists(con: duckdb.DuckDBPyConnection, schema: str, name: str) -> bool:
    row = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=? AND table_name=?",
        [schema, name],
    ).fetchone()
    return bool(row and row[0])


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat() + ("Z" if value.tzinfo is None else "")
    return str(value)


def _split_flags(s: str | None) -> list[str]:
    if not s:
        return []
    return [t for t in s.split(",") if t]


# --- Health -----------------------------------------------------------------

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "warehouse_present": warehouse_exists()}


# --- Sources ----------------------------------------------------------------

_SOURCE_TABLES: tuple[str, ...] = (
    "acq_northwind", "acq_rheinland", "acq_sunset",
    "crm", "ecommerce", "loyalty", "pos",
)


def _compute_source_info(con: duckdb.DuckDBPyConnection, name: str) -> SourceInfo:
    row = con.execute(f"SELECT COUNT(*), MAX(_ingested_at) FROM raw.{name}").fetchone()
    row_count = row[0] or 0
    last_ingested = row[1]
    rej_count = 0
    if _table_exists(con, "conformed", "_reject"):
        r = con.execute("SELECT COUNT(*) FROM conformed._reject WHERE _source=?", [name]).fetchone()
        rej_count = r[0] or 0
    null_rate = 0.0
    if _table_exists(con, "conformed", "customer"):
        r = con.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN email_normalized IS NULL THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN phone_e164 IS NULL THEN 1 ELSE 0 END) "
            "FROM conformed.customer WHERE _source=?",
            [name],
        ).fetchone()
        total = r[0] or 0
        if total:
            null_rate = ((r[1] or 0) + (r[2] or 0)) / (2 * total)
    reject_rate = rej_count / row_count if row_count else 0.0
    quality_score = max(0.0, min(1.0, 1.0 - (reject_rate + null_rate) / 2))
    return SourceInfo(
        name=name,
        row_count=row_count,
        quality_score=quality_score,
        last_ingested_at=_iso(last_ingested),
        anomaly_count=rej_count,
    )


@app.get("/api/sources", response_model=list[SourceInfo])
def list_sources() -> list[SourceInfo]:
    with _con() as con:
        if con is None:
            return []
        return [_compute_source_info(con, s) for s in _SOURCE_TABLES if _table_exists(con, "raw", s)]


# --- Customers --------------------------------------------------------------

@app.get("/api/customers", response_model=list[CustomerSummary])
def list_customers(
    q: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[CustomerSummary]:
    with _con() as con:
        if con is None or not _table_exists(con, "curated", "customer_master"):
            return []
        sql = "SELECT customer_id, full_name, n_sources, record_confidence, city, region FROM curated.customer_master"
        params: list[Any] = []
        if q:
            sql += " WHERE LOWER(COALESCE(full_name,'')) LIKE ? OR LOWER(COALESCE(city,'')) LIKE ?"
            needle = f"%{q.lower()}%"
            params.extend([needle, needle])
        sql += " ORDER BY record_confidence DESC, full_name LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return [
            CustomerSummary(
                id=r[0],
                full_name=r[1] or "",
                n_sources=r[2] or 0,
                record_confidence=float(r[3] or 0.0),
                city=r[4],
                region=r[5],
            )
            for r in con.execute(sql, params).fetchall()
        ]


_RAW_ID_COL: dict[str, str] = {
    "acq_northwind": "CUSTNO",
    "acq_rheinland": "Kundennr",
    "acq_sunset": "acct",
    "crm": "contact_id",
    "ecommerce": "customer_id",
    "loyalty": "member_id",
    "pos": "CUST_ID",
}


def _load_raw_payload(con: duckdb.DuckDBPyConnection, source: str, source_id: str) -> dict[str, Any]:
    if not _table_exists(con, "raw", source):
        return {}
    table = f"raw.{source}"
    try:
        if source == "pos" and ":" in source_id:
            base_id, row_num = source_id.split(":", 1)
            row = con.execute(
                f"SELECT _raw_payload FROM {table} WHERE CUST_ID = ? AND _source_row = ?",
                [base_id, int(row_num)],
            ).fetchone()
        else:
            id_col = _RAW_ID_COL.get(source)
            if not id_col:
                return {}
            row = con.execute(f"SELECT _raw_payload FROM {table} WHERE {id_col} = ?", [source_id]).fetchone()
        if not row or not row[0]:
            return {}
        data = json.loads(row[0])
        return {k: (None if v is None else str(v)) for k, v in data.items()}
    except (duckdb.Error, json.JSONDecodeError, ValueError):
        return {}


def _field_provenance(master: dict[str, Any]) -> list[FieldProvenance]:
    out: list[FieldProvenance] = []
    for field, label in (
        ("full_name", "full_name"),
        ("email_hash", "email"),
        ("phone_hash", "phone"),
        ("city", "city"),
        ("region", "region"),
        ("birth_date", "birth_year"),
    ):
        src = master.get(f"{field}_source") or master.get(f"{label}_source")
        conf = master.get(f"{field}_confidence") or master.get(f"{label}_confidence")
        value = master.get(field)
        if isinstance(value, (datetime,)):
            value = value.isoformat()
        if src is None and value is None:
            continue
        out.append(FieldProvenance(
            field=label,
            value=None if value is None else str(value),
            source=src or "unknown",
            confidence=float(conf or 0.0),
        ))
    return out


@app.get("/api/customers/{customer_id}", response_model=CustomerDetail)
def get_customer(customer_id: str) -> CustomerDetail:
    with _con() as con:
        if con is None or not _table_exists(con, "curated", "customer_master"):
            raise HTTPException(status_code=404, detail="warehouse empty")
        cols = [c[0] for c in con.execute("DESCRIBE curated.customer_master").fetchall()]
        row = con.execute("SELECT * FROM curated.customer_master WHERE customer_id = ?", [customer_id]).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"customer {customer_id} not found")
        master = dict(zip(cols, row))

        contributions: list[SourceContribution] = []
        xrefs = con.execute(
            "SELECT _source, _source_id FROM curated.customer_xref WHERE customer_id = ?",
            [customer_id],
        ).fetchall()
        for src, sid in xrefs:
            crow = con.execute(
                "SELECT _source_row, field_quality_flags, _ingested_at "
                "FROM conformed.customer WHERE _source = ? AND _source_id = ?",
                [src, sid],
            ).fetchone()
            payload = _load_raw_payload(con, src, sid)
            contributions.append(SourceContribution(
                source=src,
                source_id=sid,
                source_row=int(crow[0]) if crow and crow[0] is not None else 0,
                ingested_at=_iso(crow[2]) if crow else "",
                fields=payload,
                field_quality_flags=_split_flags(crow[1] if crow else None),
            ))

        bd = master.get("birth_date")
        birth_year = bd.year if hasattr(bd, "year") else None

        return CustomerDetail(
            id=customer_id,
            full_name=master.get("full_name") or "",
            city=master.get("city"),
            region=master.get("region"),
            birth_year=birth_year,
            n_sources=master.get("n_sources") or 0,
            record_confidence=float(master.get("record_confidence") or 0.0),
            fields=_field_provenance(master),
            contributions=contributions,
        )


@app.get("/api/customers/{customer_id}/lineage", response_model=LineageGraph)
def get_lineage(customer_id: str) -> LineageGraph:
    with _con() as con:
        if con is None or not _table_exists(con, "curated", "customer_master"):
            return LineageGraph(root=customer_id, nodes=[], edges=[])
        master = con.execute(
            "SELECT customer_id, full_name FROM curated.customer_master WHERE customer_id = ?",
            [customer_id],
        ).fetchone()
        if not master:
            return LineageGraph(root=customer_id, nodes=[], edges=[])
        master_node_id = f"master:{customer_id}"
        nodes: list[LineageNode] = [LineageNode(
            id=master_node_id, kind="master",
            label=f"customer_master / {master[1] or customer_id}",
            meta={"customer_id": customer_id},
        )]
        edges: list[LineageEdge] = []
        xrefs = con.execute(
            "SELECT _source, _source_id, match_method, match_score "
            "FROM curated.customer_xref WHERE customer_id = ?",
            [customer_id],
        ).fetchall()
        for src, sid, method, score in xrefs:
            xref_id = f"xref:{src}:{sid}"
            conf_id = f"conformed:{src}:{sid}"
            raw_id = f"raw:{src}:{sid}"
            nodes.append(LineageNode(id=xref_id, kind="xref", label=f"xref · {src}",
                                     meta={"method": method, "score": score}))
            nodes.append(LineageNode(id=conf_id, kind="conformed",
                                     label=f"conformed.customer ({src} {sid})"))
            nodes.append(LineageNode(id=raw_id, kind="raw", label=f"raw.{src} ({sid})"))
            edges.append(LineageEdge.model_validate({"from": master_node_id, "to": xref_id}))
            edges.append(LineageEdge.model_validate({"from": xref_id, "to": conf_id}))
            edges.append(LineageEdge.model_validate({"from": conf_id, "to": raw_id}))
        return LineageGraph(root=master_node_id, nodes=nodes, edges=edges)


# --- Review queue -----------------------------------------------------------

def _review_side(con: duckdb.DuckDBPyConnection, key: str) -> ReviewSide:
    """Build a ReviewSide from a 'source::source_id' key by reading conformed row + raw payload."""
    if "::" not in key:
        return ReviewSide(source="?", source_id=key, name=key)
    src, sid = key.split("::", 1)
    crow = con.execute(
        "SELECT first_name, last_name, full_name_normalized, email_normalized, phone_e164, "
        "street, city, region, postal_code, birth_date "
        "FROM conformed.customer WHERE _source = ? AND _source_id = ?",
        [src, sid],
    ).fetchone()
    if not crow:
        return ReviewSide(source=src, source_id=sid, name=sid)
    first, last, full_norm, email, phone, street, city, region, postal, dob = crow
    name = " ".join(p for p in (first, last) if p) or full_norm or sid
    addr_parts = [p for p in (street, city, region, postal) if p]
    address = ", ".join(addr_parts) if addr_parts else None
    return ReviewSide(
        source=src,
        source_id=sid,
        name=name,
        email=email,
        phone=phone,
        address=address,
        dob=str(dob) if dob else None,
    )


@app.get("/api/review-queue", response_model=list[ReviewPair])
def review_queue(limit: int = Query(50, ge=1, le=500)) -> list[ReviewPair]:
    with _con() as con:
        if con is None or not _table_exists(con, "curated", "customer_review"):
            return []
        rows = con.execute(
            "SELECT review_id, left_customer, right_customer, score, features "
            "FROM curated.customer_review ORDER BY score DESC LIMIT ?",
            [limit],
        ).fetchall()
        out: list[ReviewPair] = []
        for rid, left, right, score, features_json in rows:
            try:
                features = json.loads(features_json) if features_json else {}
            except json.JSONDecodeError:
                features = {}
            reason_bits = [f"{k}={v:.2f}" for k, v in features.items()] if features else []
            reason = ", ".join(reason_bits) if reason_bits else "boundary band"
            out.append(ReviewPair(
                id=rid,
                score=float(score or 0.0),
                left=_review_side(con, left),
                right=_review_side(con, right),
                reason=reason,
            ))
        return out


@app.post("/api/review/{review_id}")
def post_review(review_id: str, body: ReviewDecision) -> dict[str, Any]:
    if body.decision not in ("merge", "keep_separate"):
        raise HTTPException(status_code=400, detail="decision must be 'merge' or 'keep_separate'")
    if not warehouse_exists():
        raise HTTPException(status_code=503, detail="warehouse not built")
    con = duckdb.connect(str(DB_PATH), read_only=False)
    try:
        row = con.execute(
            "SELECT left_customer, right_customer, score FROM curated.customer_review WHERE review_id = ?",
            [review_id],
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"review {review_id} not found")
        left, right, score = row
        audit_id = str(uuid.uuid4())
        con.execute(
            "INSERT INTO curated.match_audit (audit_id, event_type, customer_id, other_id, decision, score, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [audit_id, "review_decision", left, right, body.decision, float(score or 0.0), body.note, utc_now()],
        )
        con.execute("DELETE FROM curated.customer_review WHERE review_id = ?", [review_id])
        return {"ok": True, "audit_id": audit_id}
    finally:
        con.close()


# --- Quality ----------------------------------------------------------------

def _quality_to_model(name: str, severity: str, passed: bool, detail: str, ran_at: str) -> QualityCheck:
    return QualityCheck(
        name=name,
        level=severity.upper() if severity else "INFO",
        status="pass" if passed else "fail",
        message=detail,
        ran_at=ran_at,
    )


@app.get("/api/quality/checks", response_model=list[QualityCheck])
def quality_checks() -> list[QualityCheck]:
    if REPORT_PATH.exists():
        try:
            report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
            entries = report.get("quality", [])
            ran_at = report.get("finished_at") or report.get("started_at") or ""
            return [
                _quality_to_model(
                    e["name"],
                    e["severity"] if isinstance(e["severity"], str) else e["severity"].get("value", ""),
                    bool(e["passed"]),
                    e.get("detail", ""),
                    ran_at,
                )
                for e in entries
            ]
        except (json.JSONDecodeError, KeyError):
            pass
    with _con() as con:
        if con is None:
            return []
        now = utc_now().isoformat()
        return [
            _quality_to_model(r.name, r.severity.value, r.passed, r.detail, now)
            for r in quality.run_all(con)
        ]
