"""Entry point: ingest -> conform -> quality -> match. Idempotent end-to-end."""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb

from pipeline import conform, ingest, match, quality


REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent
WAREHOUSE_DIR: Path = REPO_ROOT / "warehouse"
DB_PATH: Path = WAREHOUSE_DIR / "fabrikam.duckdb"
REPORT_PATH: Path = WAREHOUSE_DIR / "last_run_report.json"


def _json_default(o: Any) -> Any:
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    if is_dataclass(o):
        return asdict(o)
    if hasattr(o, "value"):
        return o.value
    return str(o)


def _write_report(report: dict[str, Any]) -> None:
    WAREHOUSE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, indent=2, default=_json_default),
        encoding="utf-8",
    )


def main() -> int:
    WAREHOUSE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[pipeline] opening warehouse at {DB_PATH}")
    con = duckdb.connect(str(DB_PATH))
    try:
        ingest.init_schemas(con)

        print("[pipeline] stage 1/4 ingest")
        ingest_counts = ingest.run_all(con)
        for s, n in ingest_counts.items():
            print(f"  - {s}: {n} rows")

        print("[pipeline] stage 2/4 conform")
        conform_counts = conform.run_all(con)
        for s, info in conform_counts.items():
            print(f"  - {s}: kept={info['kept']} rejected={info['rejected']}")

        print("[pipeline] stage 3/4 quality")
        checks = quality.run_all(con)
        for c in checks:
            status = "PASS" if c.passed else f"FAIL ({c.severity.value})"
            print(f"  - {c.name}: {status} - {c.detail}")

        report: dict[str, Any] = {
            "ingest": ingest_counts,
            "conform": conform_counts,
            "quality": [asdict(c) for c in checks],
        }

        try:
            quality.assert_contracts_pass(con)
        except quality.QualityFailure as e:
            print(f"[pipeline] BLOCKING quality failure: {e}", file=sys.stderr)
            report["status"] = "blocked"
            report["error"] = str(e)
            _write_report(report)
            return 1

        print("[pipeline] stage 4/4 match")
        match_counts = match.run(con)
        for k, v in match_counts.items():
            print(f"  - {k}: {v}")
        report["match"] = match_counts
        report["status"] = "ok"

        _write_report(report)
        print(f"[pipeline] done. report at {REPORT_PATH}")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
