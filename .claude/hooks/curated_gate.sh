#!/usr/bin/env bash
#
# curated_gate.sh — PreToolUse hook.
#
# Blocks any Write into warehouse/curated/** unless the deterministic quality
# contracts are green. This is the "hooks-for-guardrails, prompts-for-preferences"
# split: schema drift, null explosion, volume anomaly, and referential
# integrity are CODE, not a prompt instruction.
#
# Wire-up — add to .claude/settings.local.json:
#
#   {
#     "hooks": {
#       "PreToolUse": [
#         {
#           "matcher": "Write",
#           "hooks": [
#             { "type": "command", "command": "bash .claude/hooks/curated_gate.sh" }
#           ]
#         }
#       ]
#     }
#   }
#
# Claude Code passes the tool invocation JSON on stdin; we inspect the target
# path and only fire the contract check when the write lands under
# warehouse/curated/. Anything else: pass through.
#
# Exit codes:
#   0  — allow the write
#   2  — block (stderr is shown to Claude as the reason)

set -euo pipefail

# Read the tool-use payload from stdin (Claude Code hook contract).
payload="$(cat || true)"

# Cheap pattern match — avoids a jq dependency. We're looking for a file path
# under warehouse/curated/. If the payload doesn't reference that, allow.
if ! echo "$payload" | grep -Eq '"(file_path|path)"[[:space:]]*:[[:space:]]*"[^"]*warehouse/curated/'; then
  exit 0
fi

# Locate the repo root (this script lives at <repo>/.claude/hooks/).
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"

cd "$repo_root/backend"

# Run the contract check against the current warehouse. Read-only — we only
# want to know whether the gate is open. Any non-zero exit from Python is
# treated as a contract failure.
if ! python -c "
import duckdb
from pipeline.quality import assert_contracts_pass
con = duckdb.connect('../warehouse/fabrikam.duckdb', read_only=True)
assert_contracts_pass(con)
" 2>/tmp/curated_gate.err; then
  echo "curated_gate: quality contracts failed — blocking write into warehouse/curated/" >&2
  echo "--- reason ---" >&2
  cat /tmp/curated_gate.err >&2 || true
  exit 2
fi

exit 0
