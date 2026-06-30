#!/usr/bin/env python
"""Human-readable build report. `make report` after `make build`."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import common  # noqa: E402


def main():
    if not common.WAREHOUSE.exists():
        print("No warehouse. Run `make build` first.")
        return 1
    con = common.connect(read_only=True)
    q = lambda s: con.execute(s).fetchone()[0]

    print("\n  FABRIKAM CUSTOMER-360 — build report")
    print("  " + "=" * 52)
    quarantined = q("SELECT count(*) FROM conform_log WHERE outcome='quarantined'")
    merges = q("SELECT count(*) FROM curated_customer WHERE member_count>1")
    print(f"  raw rows           {q('SELECT count(*) FROM raw_customer')}")
    print(f"  conformed rows     {q('SELECT count(*) FROM conformed_customer')}")
    print(f"  quarantined        {quarantined}")
    print(f"  rows retried       {q('SELECT count(*) FROM conform_log WHERE retry_count>0')}")
    print(f"  golden records     {q('SELECT count(*) FROM curated_customer')}")
    print(f"  multi-source merges{merges:>4}")
    print(f"  in review queue    {q('SELECT count(*) FROM match_review_queue')}")

    print("\n  Retry reasons:")
    for et, n in con.execute(
        "SELECT error_types, count(*) FROM conform_log WHERE error_types<>'' "
        "GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall():
        print(f"    {et:<22} {n}")

    print("\n  Golden records built from the most sources:")
    for name, mc, src, conf in con.execute(
        "SELECT full_name, member_count, member_sources, match_confidence "
        "FROM curated_customer ORDER BY member_count DESC, match_confidence DESC LIMIT 6"
    ).fetchall():
        print(f"    {name[:30]:<31} x{mc}  conf {conf:.2f}  [{src}]")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
