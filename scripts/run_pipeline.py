#!/usr/bin/env python
"""Build the whole Customer-360 warehouse end to end.

    raw -> conformed -> [DQ gate] -> curated golden records

The DQ gate (Challenge 5 / The Tripwire) runs BEFORE curated is written. If a
breaking check fails, the build aborts and curated is never touched — the same
contract the PreToolUse hook enforces for interactive writes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import common, conform, dq, ingest, resolve  # noqa: E402


def main() -> int:
    with common.connect() as con:
        print("→ raw zone …")
        print("  ", json.dumps(ingest.run(con)))
        print("→ conformed zone (parse-validate-retry) …")
        print("  ", json.dumps(conform.run(con)))

        print("→ Tripwire: data-quality gate before curated …")
        report = dq.run(con, stage="pre_curated")
        print("  ", json.dumps(report["summary"]))
        if report["blocked"]:
            print("✗ BUILD ABORTED — breaking DQ checks failed:")
            for c in report["breaches"]:
                print(f"    - [{c['severity']}] {c['check']}: {c['detail']}")
            return 2

        print("→ curated zone (entity resolution → golden records) …")
        print("  ", json.dumps(resolve.run(con)))

        print("→ Tripwire: post-build curated integrity …")
        post = dq.run(con, stage="post_curated")
        print("  ", json.dumps(post["summary"]))

    print("✓ warehouse.duckdb built.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
