#!/usr/bin/env python3
"""Gate semantic retrieval proposals against governed state and task scope.

The retriever is a proposer, never an authority. It may nominate existing state
IDs with scores; this tool rejects stale, unknown, excluded, out-of-scope, or
unauthorized control items.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow sibling imports both when executed and when imported by tests.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_io import SafeIOError, atomic_write_text, require_version

import context_compile as cc


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate semantic retrieval candidates against governed state")
    parser.add_argument("state", type=Path)
    parser.add_argument("task", type=Path)
    parser.add_argument("candidates", type=Path)
    parser.add_argument("--output", "-o", type=Path)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if any candidate is rejected")
    args = parser.parse_args()
    try:
        state = cc.load_json(args.state)
        task = cc.load_json(args.task)
        candidates = cc.load_json(args.candidates)
        require_version(state, label="state")
        require_version(candidates, label="semantic candidates")
        for key in ("scope_ids", "require_ids", "exclude_ids"):
            task.setdefault(key, [])
        report = cc.gate_semantic_candidates(
            state, task, candidates, exclude_ids=set(str(x) for x in task.get("exclude_ids", []))
        )
        text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            atomic_write_text(args.output, text)
        else:
            sys.stdout.write(text)
        return 1 if args.strict and report["rejected"] else 0
    except (OSError, SafeIOError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"retrieval-gate: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
