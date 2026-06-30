---
description: Rebuild the Customer-360 warehouse and run all gates (build + eval + tests)
---

Rebuild the lakehouse end-to-end and verify every gate, in order. Stop and report at the
first failure (don't continue past a red gate).

1. `.venv/bin/python -m pytest -q tests/` — unit tests for normalizers + matcher rules.
2. `.venv/bin/python scripts/run_pipeline.py` — raw → conformed → [DQ gate] → curated.
   The DQ gate aborts the build on a breaking check; surface those breaches if it fails.
3. `.venv/bin/python eval/score_matcher.py` — the matcher scorecard (the CI gate).
   If precision/recall/false-confidence breach thresholds, show the failing pairs.
4. `.venv/bin/python scripts/report.py` — print the build report.

Then summarize: rows in/out, retries, golden-record count, review-queue size, and whether
all gates are green. If anything is red, name the exact check and the fix location
(`resolve.py` for matching, `conform.py` for parsing, `contracts.py` for schema).
