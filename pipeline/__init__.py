"""Fabrikam Customer-360 lakehouse pipeline.

Zones (medallion / lakehouse):
    raw       -> exactly what the source emitted, plus lineage metadata. Immutable.
    conformed -> one canonical customer schema, cleaned & standardized. Source rows still 1:1.
    curated   -> golden customer records after entity resolution. One row per real person.

Everything lands in a single DuckDB file (warehouse.duckdb) so the whole thing
runs on a laptop with no infrastructure.
"""

__all__ = ["common", "contracts", "ingest", "conform", "resolve", "dq", "profile"]
