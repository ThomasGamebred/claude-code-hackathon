# Raw zone

**Rule:** verbatim from source, append-only, immutable.

- **No transformations.** No type coercion, no value rewriting, no normalization. The raw zone is the audit trail.
- **Every row must carry lineage**: `_source`, `_source_file`, `_source_row`, `_ingested_at`, `_raw_payload`.
- **Mutation**: in production, append-only. In this hackathon, truncate-and-reload per source is allowed because the source files are themselves immutable — re-running produces the same state.
- **PII**: stored exactly as the source emitted it. Do not hash or tokenize here.
- **Retention**: indefinite.
- **Who reads it**: data engineers only.

If you find yourself wanting to clean a value here, you're in the wrong zone — that work belongs in `conformed`.
