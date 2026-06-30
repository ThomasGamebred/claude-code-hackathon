"""Smoke tests for the Fabrikam MCP server.

These verify the structured-error contract every tool must honor when the
warehouse file is missing, and that get_source_schema works without a
warehouse (its catalog lives in code).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="mcp SDK not installed")
pytest.importorskip("duckdb", reason="duckdb not installed")

from fabrikam_mcp.server import (  # noqa: E402
    SEVEN_SOURCES,
    TOOLS_BY_NAME,
    Warehouse,
    call_tool,
)


@pytest.fixture
def missing_warehouse(tmp_path: Path) -> Warehouse:
    """A Warehouse pointing at a path that does not exist."""
    path = tmp_path / "definitely-not-here.duckdb"
    assert not path.exists()
    return Warehouse(path=path)


# Tools that must hard-fail with WAREHOUSE_MISSING when the file is absent.
# get_source_schema is intentionally NOT in this set — its data lives in code.
TOOLS_NEEDING_WAREHOUSE: tuple[tuple[str, dict], ...] = (
    ("list_sources", {}),
    ("preview_table", {"table": "raw.crm", "limit": 1}),
    ("find_record", {"query": "doe"}),
    ("trace_lineage", {"customer_id": "some-uuid"}),
    ("quality_status", {}),
)


@pytest.mark.parametrize("name,args", TOOLS_NEEDING_WAREHOUSE)
def test_tool_returns_warehouse_missing(name: str, args: dict, missing_warehouse: Warehouse) -> None:
    body = call_tool(name, args, missing_warehouse)
    assert body["isError"] is True, body
    assert body["reason_code"] == "WAREHOUSE_MISSING", body
    assert "expected_path" in body


def test_get_source_schema_works_without_warehouse(missing_warehouse: Warehouse) -> None:
    body = call_tool("get_source_schema", {"source": "crm"}, missing_warehouse)
    assert body["isError"] is False, body
    data = body["data"]
    assert data["source"] == "crm"
    assert "columns" in data and len(data["columns"]) > 0
    assert "known_issues" in data and isinstance(data["known_issues"], list)
    assert data["warehouse_table"] == "raw.crm"


def test_get_source_schema_unknown_source(missing_warehouse: Warehouse) -> None:
    body = call_tool("get_source_schema", {"source": "not_a_source"}, missing_warehouse)
    assert body["isError"] is True
    assert body["reason_code"] == "UNKNOWN_SOURCE"
    assert set(body["known"]) == set(SEVEN_SOURCES)


def test_unknown_tool(missing_warehouse: Warehouse) -> None:
    body = call_tool("nope", {}, missing_warehouse)
    assert body["isError"] is True
    assert body["reason_code"] == "UNKNOWN_TOOL"


def test_bad_arguments_validation(missing_warehouse: Warehouse) -> None:
    # find_record requires a min_length=2 query.
    body = call_tool("find_record", {"query": "a"}, missing_warehouse)
    assert body["isError"] is True
    assert body["reason_code"] == "BAD_ARGUMENTS"
    assert "errors" in body


def test_preview_table_rejects_unknown_table(tmp_path: Path) -> None:
    # Use a real (but empty) DuckDB so we get past the warehouse check and hit
    # the allow-list branch.
    import duckdb

    path = tmp_path / "empty.duckdb"
    con = duckdb.connect(str(path))
    con.close()
    wh = Warehouse(path=path)

    body = call_tool(
        "preview_table",
        {"table": "raw.does_not_exist", "limit": 1},
        wh,
    )
    assert body["isError"] is True
    assert body["reason_code"] == "TABLE_NOT_FOUND"
    assert "allowed" in body


def test_preview_table_rejects_bad_where(tmp_path: Path) -> None:
    import duckdb

    path = tmp_path / "empty.duckdb"
    con = duckdb.connect(str(path))
    # Create the table so we get past TABLE_NOT_FOUND down into the WHERE check.
    con.execute("CREATE SCHEMA raw; CREATE TABLE raw.crm (contact_id VARCHAR);")
    con.close()
    wh = Warehouse(path=path)

    body = call_tool(
        "preview_table",
        {"table": "raw.crm", "limit": 1, "where": "1=1; DROP TABLE raw.crm"},
        wh,
    )
    assert body["isError"] is True
    assert body["reason_code"] == "BAD_WHERE"


def test_tool_descriptions_cover_required_phrases() -> None:
    """The descriptions are the deliverable — assert key contract phrases.

    These checks are loose on purpose: they protect against accidental
    deletion of the load-bearing parts of each description without locking
    the wording in too tightly.
    """
    pt = TOOLS_BY_NAME["preview_table"].description
    assert "WHERE" in pt
    assert "Does NOT" in pt or "does NOT" in pt
    assert "read-only" in pt.lower() or "select" in pt.lower()

    fr = TOOLS_BY_NAME["find_record"].description
    assert "trace_lineage" in fr  # cross-references the right next step

    tl = TOOLS_BY_NAME["trace_lineage"].description
    assert "customer_id" in tl
    assert "find_record" in tl  # cross-references the discovery tool

    for name in ("list_sources", "preview_table", "find_record", "trace_lineage", "quality_status"):
        assert "WAREHOUSE_MISSING" in TOOLS_BY_NAME[name].description or "make pipeline" in TOOLS_BY_NAME[name].description


def test_all_six_tools_registered() -> None:
    assert set(TOOLS_BY_NAME) == {
        "list_sources",
        "preview_table",
        "find_record",
        "trace_lineage",
        "get_source_schema",
        "quality_status",
    }
