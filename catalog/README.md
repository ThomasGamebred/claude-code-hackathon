# Data Catalog

Analyst-facing entries for the core entities. Each entry answers four questions —
*what is this, where did it come from, can I trust it, what does the term mean here* —
and links to the producer **contract** in [`pipeline/contracts.py`](../pipeline/contracts.py)
so you can see what each source actually promises.

| Entity | Table | Entry |
|---|---|---|
| **Customer** (golden record) | `curated_customer` | [customer.md](customer.md) |
| Conformed customer (per-source, pre-merge) | `conformed_customer` | see [customer.md → lineage](customer.md#where-did-it-come-from) |
| Match review queue (uncertain pairs) | `match_review_queue` | borderline pairs awaiting human adjudication |

## How to explore
- `make build` then query `warehouse.duckdb` directly, or
- use the **lineage MCP server** (`make mcp`): `find_record`, `preview_table`,
  `trace_lineage`, `get_source_schema` — see [`mcp/server.py`](../mcp/server.py).

## The one definition that matters
**"Customer" = one physical person**, resolved across all sources — not an account, not a
transaction, not a row in any one system. One person with five logins is one customer here.
Every golden record tells you how confident we are it's really one person
(`match_confidence`) and how much the sources agreed on each field (`field_confidence`).
