"""Fabrikam MCP server — trace and preview tools over the Single-Customer-View lakehouse.

Exposes six tools (list_sources, preview_table, find_record, trace_lineage,
get_source_schema, quality_status) backed by a read-only DuckDB connection to
``warehouse/fabrikam.duckdb``. The tool descriptions are the contract: a fresh
Claude session should be able to pick the right tool on the first try.
"""

__version__ = "0.1.0"
