# Data-quality rules — break vs. alert

Every check declares up front whether it **breaks** the pipeline (refuse to propagate
corruption) or **alerts** (record it, a human should look, but don't stop the line).
The decision rule: *would shipping this row corrupt a downstream consumer's correctness?*
If yes → break. If it's a quality signal that a human should triage → alert.
Implemented in `pipeline/dq.py`; enforced by the pipeline gate and the `PreToolUse` hook.

## Pre-curated (raw + conformed)
| Check | Severity | Why that severity |
|---|---|---|
| `schema_drift` — key column missing | **break** | Lineage depends on the natural key; without it we can't trace or dedupe. Refuse. |
| `schema_drift` — other columns added/removed | alert | Sources evolve; a new column isn't corruption, it's news. |
| `null_rate[email/phone/dob/full_name]` | alert | Sparse fields are normal; a spike means glance, not halt. |
| `volume[source]` — ±30% vs baseline | alert | A volume swing might be a bad export or a real surge — human judgement. |
| `ref_integrity[loyalty.pos_customer_id → pos]` | alert | A dangling FK is a finding to chase, not a reason to reject the whole load. (10 found.) |

## Curated contract (enforced before any write to the trusted zone)
| Check | Severity | Why |
|---|---|---|
| required columns present | **break** | Consumers query these by name; a missing column breaks every downstream query. |
| `non_null[golden_id, match_confidence, member_count]` | **break** | A golden record without an id/confidence/size is not a golden record. |
| `range[match_confidence ∈ 0..1]` | **break** | A confidence outside [0,1] is a bug; it would corrupt trust filters. |
| `range[member_count ∈ 1..100]` | **break** | 0 members = phantom record; >100 = a runaway merge. |
| `unique[golden_id]` | **break** | Duplicate golden ids double-count customers. |
| `has_identity` (name OR email OR phone) | **break** | A record with no identity anchor can't be a person. |

**Enforcement is layered:**
1. `scripts/run_pipeline.py` runs pre-curated checks as a **gate** — a break aborts the
   build before curated is touched.
2. `hooks/curated_guard.py` (`PreToolUse`) runs the curated contract before any manual
   `Write`/`Edit`/SQL write into the curated zone and **blocks** on a break.
3. CI runs `make eval` (the matcher scorecard) as a separate gate on every push.
