#!/usr/bin/env python3
"""Context Lint for DraftLedger.

Standard-library only. Validates semantic invariants that JSON Schema alone
cannot express: dangling references, stale decision dependencies, supersession
cycles, and ambiguous active instructions.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

# Allow sibling imports both when executed and when imported by tests.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_io import SafeIOError, read_json as safe_read_json, require_version


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str


SEVERITY_ORDER = {"ERROR": 3, "WARN": 2, "INFO": 1}


def load_state(path: Path) -> dict[str, Any]:
    return safe_read_json(path)


def by_id(items: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(x.get("id")): x for x in items if x.get("id")}


def add(findings: list[Finding], severity: str, code: str, message: str) -> None:
    findings.append(Finding(severity, code, message))


def lint(state: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    groups = {
        "F": state.get("facts", []),
        "A": state.get("assumptions", []),
        "I": state.get("instructions", []),
        "D": state.get("decisions", []),
        "O": state.get("open_items", []),
    }

    # Basic structure and duplicate IDs.
    seen: dict[str, str] = {}
    for prefix, items in groups.items():
        if not isinstance(items, list):
            add(findings, "ERROR", "STRUCTURE", f"{prefix} registry must be a list")
            continue
        for item in items:
            if not isinstance(item, dict):
                add(findings, "ERROR", "STRUCTURE", f"{prefix} registry contains a non-object item")
                continue
            item_id = item.get("id")
            if not item_id:
                add(findings, "ERROR", "MISSING_ID", f"{prefix} item is missing an id")
                continue
            if item_id in seen:
                add(findings, "ERROR", "DUPLICATE_ID", f"{item_id} appears in both {seen[item_id]} and {prefix}")
            else:
                seen[item_id] = prefix

    facts = by_id(groups.get("F", []))
    assumptions = by_id(groups.get("A", []))
    instructions = by_id(groups.get("I", []))
    decisions = by_id(groups.get("D", []))
    open_items = by_id(groups.get("O", []))

    # Trust boundary: control authority is reserved for governed instructions.
    registry_items = {
        "facts": facts,
        "assumptions": assumptions,
        "instructions": instructions,
        "decisions": decisions,
        "open_items": open_items,
    }
    for registry, items in registry_items.items():
        for item_id, item in items.items():
            authority = item.get("authority")
            trust = item.get("trust_level")
            origin = item.get("origin")
            if authority is None:
                add(findings, "WARN", "AUTHORITY_MISSING", f"{item_id} has no explicit authority metadata")
            if trust is None:
                add(findings, "WARN", "TRUST_LEVEL_MISSING", f"{item_id} has no explicit trust_level metadata")
            if not isinstance(origin, dict) or not origin.get("kind"):
                add(findings, "WARN", "ORIGIN_MISSING", f"{item_id} has no explicit origin.kind provenance")
            if registry == "instructions":
                if authority not in (None, "control"):
                    add(findings, "ERROR", "INSTRUCTION_NOT_CONTROL", f"{item_id} is an instruction but authority={authority!r}")
                if item.get("status") == "active" and trust is not None and trust not in ("trusted", "reviewed"):
                    add(findings, "ERROR", "UNTRUSTED_CONTROL", f"{item_id} is active control state with trust_level={trust!r}")
            elif authority == "control":
                add(findings, "ERROR", "DATA_AUTHORITY_ESCALATION", f"{item_id} is in {registry} but claims control authority")

    # Assumptions should have an explicit validation path while active.
    for item_id, item in assumptions.items():
        if item.get("status") == "active" and not str(item.get("validation_condition", "")).strip():
            add(findings, "WARN", "ASSUMPTION_NO_VALIDATION", f"{item_id} is active but has no validation_condition")
        if item.get("status") == "confirmed" and not item.get("promoted_to"):
            add(findings, "WARN", "CONFIRMED_NOT_PROMOTED", f"{item_id} is confirmed but has no promoted_to fact reference")
        promoted_to = item.get("promoted_to")
        if promoted_to and promoted_to not in facts:
            add(findings, "ERROR", "DANGLING_PROMOTION", f"{item_id} promoted_to references missing fact {promoted_to}")

    # Instruction lineage and collisions.
    for item_id, item in instructions.items():
        for field in ("supersedes", "superseded_by"):
            ref = item.get(field)
            if ref and ref not in instructions:
                add(findings, "ERROR", "DANGLING_INSTRUCTION_REF", f"{item_id}.{field} references missing instruction {ref}")
        if item.get("status") == "active" and item.get("superseded_by"):
            add(findings, "ERROR", "ACTIVE_BUT_SUPERSEDED", f"{item_id} is active but also superseded_by {item.get('superseded_by')}")

    # Detect supersession cycles.
    for start in instructions:
        trail: list[str] = []
        current = start
        while current in instructions:
            if current in trail:
                cycle = " -> ".join(trail[trail.index(current):] + [current])
                add(findings, "ERROR", "SUPERSESSION_CYCLE", f"Instruction supersession cycle: {cycle}")
                break
            trail.append(current)
            nxt = instructions[current].get("superseded_by")
            if not nxt:
                break
            current = str(nxt)

    # Same key/scope active twice is almost always ambiguous.
    active_keys: dict[tuple[str, str, str], str] = {}
    for item_id, item in instructions.items():
        if item.get("status") != "active" or not item.get("key"):
            continue
        sig = (str(item.get("key")), str(item.get("scope")), str(item.get("scope_id") or ""))
        if sig in active_keys:
            add(findings, "ERROR", "ACTIVE_INSTRUCTION_COLLISION", f"{active_keys[sig]} and {item_id} are both active for key={sig[0]!r}, scope={sig[1]!r}, scope_id={sig[2]!r}")
        else:
            active_keys[sig] = item_id

    # Decision lifecycle and revalidation provenance.
    for did, decision in decisions.items():
        status = decision.get("status")
        if status == "needs_review":
            if not str(decision.get("review_reason", "")).strip():
                add(findings, "WARN", "REVIEW_REASON_MISSING", f"{did} is needs_review but has no review_reason")
            if not (decision.get("review_triggered_by") or []):
                add(findings, "WARN", "REVIEW_TRIGGER_MISSING", f"{did} is needs_review but has no review_triggered_by provenance")
        elif status == "active":
            if decision.get("review_triggered_by"):
                add(findings, "WARN", "ACTIVE_REVIEW_RESIDUE", f"{did} is active but still carries review_triggered_by")
            if str(decision.get("review_reason", "")).strip():
                add(findings, "WARN", "ACTIVE_REVIEW_RESIDUE", f"{did} is active but still carries review_reason")

        if status == "superseded":
            replacement = decision.get("superseded_by")
            if not replacement:
                add(findings, "WARN", "SUPERSEDED_DECISION_NO_REPLACEMENT", f"{did} is superseded but has no superseded_by")
            elif replacement not in decisions:
                add(findings, "ERROR", "DANGLING_DECISION_SUPERSESSION", f"{did}.superseded_by references missing decision {replacement}")

        history = decision.get("validation_history", []) or []
        if not isinstance(history, list):
            add(findings, "ERROR", "INVALID_VALIDATION_HISTORY", f"{did}.validation_history must be an array")
        else:
            for index, event in enumerate(history):
                if not isinstance(event, dict):
                    add(findings, "ERROR", "INVALID_VALIDATION_HISTORY", f"{did}.validation_history[{index}] is not an object")
                    continue
                outcome = event.get("outcome")
                if outcome == "superseded":
                    replacement = event.get("replacement_decision_id")
                    if replacement and replacement not in decisions:
                        add(findings, "ERROR", "DANGLING_VALIDATION_REPLACEMENT", f"{did} validation history references missing decision {replacement}")
                open_id = event.get("open_item_id")
                if open_id and open_id not in open_items:
                    add(findings, "ERROR", "DANGLING_VALIDATION_OPEN_ITEM", f"{did} validation history references missing open item {open_id}")

    # Decision dependency integrity and stale dependencies.
    for decision in groups.get("D", []):
        if not isinstance(decision, dict) or not decision.get("id"):
            continue
        did = str(decision["id"])
        if decision.get("status") not in ("active", "needs_review"):
            continue

        for fid in decision.get("facts_used", []) or []:
            fact = facts.get(fid)
            if not fact:
                add(findings, "ERROR", "DANGLING_FACT_DEP", f"{did} references missing fact {fid}")
            elif fact.get("status") != "active":
                add(findings, "WARN", "STALE_FACT_DEP", f"{did} depends on {fid}, whose status is {fact.get('status')}")

        for aid in decision.get("assumptions_used", []) or []:
            assumption = assumptions.get(aid)
            if not assumption:
                add(findings, "ERROR", "DANGLING_ASSUMPTION_DEP", f"{did} references missing assumption {aid}")
            elif assumption.get("status") in ("rejected", "expired"):
                add(findings, "ERROR", "INVALID_ASSUMPTION_DEP", f"{did} depends on {aid}, whose status is {assumption.get('status')}")
            elif assumption.get("status") == "active":
                add(findings, "INFO", "PROVISIONAL_DECISION", f"{did} still depends on active assumption {aid}")

        for iid in decision.get("instructions_used", []) or []:
            instruction = instructions.get(iid)
            if not instruction:
                add(findings, "ERROR", "DANGLING_INSTRUCTION_DEP", f"{did} references missing instruction {iid}")
            elif instruction.get("status") != "active":
                add(findings, "WARN", "STALE_INSTRUCTION_DEP", f"{did} was made under {iid}, whose status is {instruction.get('status')}; revalidation may be needed")

    if not findings:
        add(findings, "INFO", "CLEAN", "No semantic state-governance issues detected")

    # Deduplicate cycle reports and any exact repeated finding.
    unique = {(f.severity, f.code, f.message): f for f in findings}
    return sorted(unique.values(), key=lambda f: (-SEVERITY_ORDER[f.severity], f.code, f.message))


def print_text(findings: list[Finding]) -> None:
    counts = {k: sum(f.severity == k for f in findings) for k in ("ERROR", "WARN", "INFO")}
    print(f"Context Lint: {counts['ERROR']} error(s), {counts['WARN']} warning(s), {counts['INFO']} info")
    for f in findings:
        print(f"[{f.severity}] {f.code}: {f.message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint DraftLedger JSON state")
    parser.add_argument("state", type=Path, help="Path to .agent-state/state.json")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit findings as JSON")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on warnings as well as errors")
    args = parser.parse_args()

    try:
        state = load_state(args.state)
        require_version(state, label="state")
        findings = lint(state)
    except (OSError, json.JSONDecodeError, SafeIOError, ValueError) as exc:
        print(f"context-lint: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps([f.__dict__ for f in findings], ensure_ascii=False, indent=2))
    else:
        print_text(findings)

    has_error = any(f.severity == "ERROR" for f in findings)
    has_warn = any(f.severity == "WARN" for f in findings)
    return 1 if has_error or (args.strict and has_warn) else 0


if __name__ == "__main__":
    raise SystemExit(main())
