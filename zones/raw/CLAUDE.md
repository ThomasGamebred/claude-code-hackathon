# CLAUDE.md — RAW zone

**Rule of the zone: keep exactly what the source emitted. You cannot fix what you didn't keep.**

- **Mutation:** none. Append-only in spirit. `ingest.py` stores the source payload
  verbatim as JSON, plus lineage (`source_system`, `source_record_id`, `source_file`,
  `ingest_seq`, `lineage_id`). No type coercion, no cleaning, no dedup.
- **Encoding:** read with the source's declared encoding and `errors="replace"`. A bad
  byte must never abort a load; the `�` it leaves behind is itself a signal for the DQ layer.
- **Rejection:** raw rejects nothing. Even an all-empty row gets a synthesized key so its
  lineage still resolves. Validation and quarantine happen downstream in `conform`.
- **Retention:** indefinite. Raw is the system of record for "what actually arrived".
- **PII:** raw contains unmasked PII (emails, phones, DOBs). Treat it as the most
  sensitive zone. Never copy raw rows into logs, the catalog, or the presentation.

If you're tempted to "just clean this one field on the way in" — don't. That's the
conformed zone's job.
