#!/usr/bin/env python3
"""
PreToolUse Hook: Blockiert direkte Schreibzugriffe auf data/curated/.

Erlaubt ist nur das Schreiben via pipelines/golden_record_builder.py.
Direktes Editieren durch Claude ist ein harter Stopp — nicht überredbar.

Warum Hook statt CLAUDE.md-Regel: Hooks sind deterministisch. Eine Prompt-Regel
kann Claude durch Argumentation umgehen. Ein Hook nicht.
"""
import json
import sys


BLOCKED_PATH = "data/curated"
ALLOWED_WRITER = "pipelines/golden_record_builder.py"

WRITE_TOOLS = {"Write", "Edit", "NotebookEdit"}
BASH_WRITE_COMMANDS = {"cp", "mv", "tee", "touch", ">", ">>"}


def is_curated_target(tool_name: str, tool_input: dict) -> bool:
    if tool_name in WRITE_TOOLS:
        path = tool_input.get("file_path", "")
        return BLOCKED_PATH in str(path)

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if BLOCKED_PATH in command:
            # Erlaube explizit den golden_record_builder
            if ALLOWED_WRITER in command:
                return False
            # Blockiere alles andere das curated/ berührt
            return any(cmd in command for cmd in BASH_WRITE_COMMANDS) or ">" in command

    return False


def main():
    hook_input = json.load(sys.stdin)
    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    if is_curated_target(tool_name, tool_input):
        print(json.dumps({
            "decision": "block",
            "reason": (
                f"Direktes Schreiben in {BLOCKED_PATH}/ ist gesperrt. "
                f"Nutze {ALLOWED_WRITER} — das führt zuerst quality_checks.py aus "
                "und schreibt nur bei grünem Check."
            )
        }))
        sys.exit(0)

    print(json.dumps({"decision": "approve"}))


if __name__ == "__main__":
    main()
