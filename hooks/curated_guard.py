#!/usr/bin/env python
"""PreToolUse guard for the CURATED zone (Challenge 5 / ADR-0005).

Deterministic guardrail. Wired in .claude/settings.json as a PreToolUse hook on
Write|Edit|Bash. It BLOCKS any tool call that would write into the curated zone
(zones/curated, curated_customer, or a SQL INSERT/UPDATE/CREATE against curated)
unless the curated schema contract currently passes.

Why a hook and not a prompt: "curated must satisfy its contract" is an invariant, not
a preference. Invariants are enforced, not requested. See ADR-0005.

Protocol: reads the tool call as JSON on stdin. To block, exit 2 with a reason on
stderr (Claude Code surfaces it and refuses the call). Exit 0 to allow.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CURATED_SIGNALS = re.compile(
    r"zones/curated|curated_customer|curated[_/]", re.IGNORECASE)
WRITE_SQL = re.compile(r"\b(insert|update|delete|create\s+(or\s+replace\s+)?table)\b",
                       re.IGNORECASE)


def _touches_curated(tool: str, ti: dict) -> bool:
    blob = json.dumps(ti)
    if not CURATED_SIGNALS.search(blob):
        return False
    if tool in ("Write", "Edit", "MultiEdit"):
        return bool(CURATED_SIGNALS.search(ti.get("file_path", "")))
    if tool == "Bash":
        cmd = ti.get("command", "")
        return bool(WRITE_SQL.search(cmd) and CURATED_SIGNALS.search(cmd))
    return True


def _contract_passes() -> tuple[bool, str]:
    try:
        from pipeline import common, dq  # local import so the hook is cheap when idle
        if not common.WAREHOUSE.exists():
            return True, "no warehouse yet (nothing to protect)"
        with common.connect(read_only=True) as con:
            tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if "curated_customer" not in tables:
                return True, "curated_customer not built yet"
            report = dq.run(con, stage="post_curated")
        if report["blocked"]:
            bad = "; ".join(f"{c['check']} ({c['detail']})" for c in report["breaches"])
            return False, bad
        return True, "curated contract passes"
    except Exception as e:  # never crash the user's tool call on a hook bug
        return True, f"guard skipped (self-error: {e})"


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except Exception:
        return 0
    tool = event.get("tool_name", "")
    ti = event.get("tool_input", {}) or {}
    if not _touches_curated(tool, ti):
        return 0
    ok, detail = _contract_passes()
    if ok:
        return 0
    sys.stderr.write(
        "BLOCKED by curated_guard (PreToolUse): writing to the curated zone is not "
        "allowed while the curated schema contract is failing.\n"
        f"Contract breaches: {detail}\n"
        "Fix the rule in resolve.py/conform.py and rebuild (make build), then retry.\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
