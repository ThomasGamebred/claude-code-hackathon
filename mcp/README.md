# fabrikam-mcp

An MCP server exposing **trace and preview** tools over the Fabrikam
Single-Customer-View lakehouse. This is Challenge 8 ("The Trace") from the
data-engineering scenario: given one bad value in a report, walk it back to
the source row programmatically.

## Install

```bash
pip install -e ./mcp
```

The console script `fabrikam-mcp` is then on PATH and speaks the MCP stdio
protocol.

## Register with Claude Code

Add to your Claude Code MCP configuration (e.g. `.mcp.json` at the repo root,
or your user-level `~/.claude/mcp.json`):

```json
{
  "mcpServers": {
    "fabrikam": {
      "command": "fabrikam-mcp",
      "args": []
    }
  }
}
```

The server opens `warehouse/fabrikam.duckdb` **read-only** when it exists.
If the warehouse hasn't been built yet (`make pipeline` from the repo root),
every tool returns a structured error with `reason_code = "WAREHOUSE_MISSING"`.

Override the warehouse path via the `FABRIKAM_WAREHOUSE` environment variable
(useful for tests against a fixture file).

## Tools

| Tool                | Cardinality of result          | Reads     | Use when                                                                  |
|---------------------|--------------------------------|-----------|---------------------------------------------------------------------------|
| `list_sources`      | 7 source rows                  | `raw.*`   | You don't know which sources exist or whether ingestion ran.              |
| `preview_table`     | up to 200 rows                 | any zone  | You already know the table; you want to eyeball it with an optional WHERE.|
| `find_record`       | many rows (one per source hit) | `conformed.customer` | You have a name/email/phone and need to discover the person.   |
| `trace_lineage`     | one nested tree                | all zones | You have a curated `customer_id` and want raw provenance.                 |
| `get_source_schema` | one source description         | code only | You're about to write a conform-layer change.                             |
| `quality_status`    | a list of checks               | curated   | You need to know whether curated is safe to trust right now.              |

Full descriptions (with input formats and edge cases) live on the tool objects
themselves — that's the contract a fresh Claude session reads to pick the
right tool on the first try.

## Why these tools

### Why six, not twelve

The cert guidance is explicit: small, well-described tool surfaces beat large
ones for first-try selection accuracy. Six is the smallest set that covers the
Challenge-8 user journey end-to-end:

1. *"What sources do we have?"* -> `list_sources`
2. *"Find John Doe."* -> `find_record`
3. *"Where did this curated row come from?"* -> `trace_lineage`
4. *"Show me the raw data for source X."* -> `preview_table`
5. *"What does source X look like before I change conform?"* -> `get_source_schema`
6. *"Are the numbers I'm looking at safe?"* -> `quality_status`

Anything else (e.g. "describe the conformed schema") is reachable by composition
(`preview_table conformed.customer LIMIT 1` gives you the columns).

### Why `find_record` and `trace_lineage` are separate

Different result cardinality, different intent.

- `find_record` is **one-to-many**: you give it a fragment, it gives you a list
  of candidates spread across sources. It's discovery.
- `trace_lineage` is **one-to-tree**: you give it a single resolved
  `customer_id`, it gives you provenance back to raw. It's drill-down.

Merging them would force one tool to do two jobs and inflate its description.
Worse, an agent given a vague query would fall into the trap of trying to
"trace" something it hasn't found yet. Keeping them split makes the workflow
obvious: `find_record` -> pick a candidate -> resolve `customer_id` via
`curated.customer_xref` (visible in the `find_record` result) -> `trace_lineage`.

### Why `preview_table` is intentionally not a SQL passthrough

A general "run any SQL" tool would be a bad fit for an LLM client:

- **Over-broad queries.** An agent given `run_sql` will write five-table joins
  with `SELECT *` and dump 50k rows into context. We saw this empirically.
- **Injection-shaped surface.** Even with read-only DuckDB, accepting arbitrary
  SQL means accepting `ATTACH 'http://...'` and similar exfiltration vectors.
- **No safety net on selection.** When the right tool is "preview a table",
  the agent picks it. When the right tool is "run SQL", the agent always picks
  it — because SQL subsumes preview.

So `preview_table` is `SELECT * FROM <allow-listed table> [WHERE <sanitized>] LIMIT N`,
and nothing else. The allow-list is the set of named lakehouse tables; the
WHERE body is filtered for DDL/DML keywords (belt-and-braces, since the
connection is read-only anyway). Cross-table reasoning lives in `find_record`
and `trace_lineage`, which encode the joins you actually want.

### Why hashed PII stays hashed

`trace_lineage` returns the raw row at the leaf — that *does* contain
unhashed PII, because that's the point of lineage. The curated row returned
at the root still uses `email_hash` / `phone_hash`; the tool does not un-hash.
Anyone with the MCP access can already read raw via `preview_table`, so the
hashing remains a curated-zone property, not an access-control story.

## Development

```bash
pip install -e "./mcp[dev]"
pytest mcp/tests
```

Tests use a tmp `FABRIKAM_WAREHOUSE` path so they don't depend on a built
warehouse.
