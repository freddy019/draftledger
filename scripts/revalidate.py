#!/usr/bin/env python3
"""Decision Revalidation Workflow for DraftLedger.

Turns ``needs_review`` decisions into an explicit review plan, then applies a
human/agent-authored resolution without silently assuming that a replacement
premise preserves the old conclusion.

Standard-library only.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Allow sibling imports both when executed and when imported by tests.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_io import SafeIOError, atomic_write_json, read_json as safe_read_json, require_version

DECISION_ID_RE = re.compile(r"^D-[0-9]{3,}$")


def load_json(path: Path) -> dict[str, Any]:
    return safe_read_json(path)


def by_id(items: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id")): item
        for item in items
        if isinstance(item, dict) and item.get("id")
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def follow_supersession(
    start_id: str,
    registry: dict[str, dict[str, Any]],
    *,
    active_status: str = "active",
) -> tuple[str | None, list[str], str | None]:
    """Follow ``superseded_by`` until an active item is found.

    Returns ``(replacement_id, chain, error)``. ``replacement_id`` is None when
    no safe deterministic replacement exists.
    """
    chain: list[str] = [start_id]
    current = registry.get(start_id)
    if current is None:
        return None, chain, f"{start_id} is missing"

    seen = {start_id}
    while True:
        if current.get("status") == active_status:
            return str(current.get("id")), chain, None
        nxt = current.get("superseded_by")
        if not nxt:
            return None, chain, f"{chain[-1]} has status={current.get('status')} and no active successor"
        nxt = str(nxt)
        if nxt in seen:
            chain.append(nxt)
            return None, chain, "supersession cycle detected"
        seen.add(nxt)
        chain.append(nxt)
        current = registry.get(nxt)
        if current is None:
            return None, chain, f"supersession chain points to missing item {nxt}"


def dependency_analysis(
    dep_id: str,
    facts: dict[str, dict[str, Any]],
    assumptions: dict[str, dict[str, Any]],
    instructions: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Describe the current validity and any deterministic successor candidate."""
    if dep_id.startswith("F-"):
        item = facts.get(dep_id)
        if item is None:
            return {
                "dependency_id": dep_id,
                "registry": "facts",
                "status": "missing",
                "action": "block",
                "replacement_id": None,
                "reason": f"{dep_id} is missing from current state",
            }
        if item.get("status") == "active":
            return {
                "dependency_id": dep_id,
                "registry": "facts",
                "status": "active",
                "action": "retain_and_recheck",
                "replacement_id": dep_id,
                "reason": "Fact is still active; if it changed in place, the decision still needs semantic review.",
            }
        replacement, chain, error = follow_supersession(dep_id, facts)
        return {
            "dependency_id": dep_id,
            "registry": "facts",
            "status": item.get("status"),
            "action": "candidate_replacement" if replacement and replacement != dep_id else "block",
            "replacement_id": replacement if replacement != dep_id else None,
            "lineage": chain,
            "reason": (
                f"Candidate active fact is {replacement}; replacement is not automatic validation."
                if replacement and replacement != dep_id
                else error or "No active replacement found."
            ),
        }

    if dep_id.startswith("A-"):
        item = assumptions.get(dep_id)
        if item is None:
            return {
                "dependency_id": dep_id,
                "registry": "assumptions",
                "status": "missing",
                "action": "block",
                "replacement_id": None,
                "reason": f"{dep_id} is missing from current state",
            }
        status = item.get("status")
        if status == "active":
            return {
                "dependency_id": dep_id,
                "registry": "assumptions",
                "status": status,
                "action": "retain_and_recheck",
                "replacement_id": dep_id,
                "reason": "Assumption remains active and provisional.",
            }
        if status == "confirmed":
            promoted = item.get("promoted_to")
            fact = facts.get(str(promoted)) if promoted else None
            if fact and fact.get("status") == "active":
                return {
                    "dependency_id": dep_id,
                    "registry": "assumptions",
                    "status": status,
                    "action": "promote_to_fact_candidate",
                    "replacement_id": str(promoted),
                    "replacement_registry": "facts",
                    "reason": f"Assumption was confirmed and promoted to active fact {promoted}.",
                }
            return {
                "dependency_id": dep_id,
                "registry": "assumptions",
                "status": status,
                "action": "block",
                "replacement_id": None,
                "reason": "Confirmed assumption has no active promoted fact.",
            }
        return {
            "dependency_id": dep_id,
            "registry": "assumptions",
            "status": status,
            "action": "block",
            "replacement_id": None,
            "reason": f"Assumption status={status}; no deterministic successor is defined.",
        }

    if dep_id.startswith("I-"):
        item = instructions.get(dep_id)
        if item is None:
            return {
                "dependency_id": dep_id,
                "registry": "instructions",
                "status": "missing",
                "action": "block",
                "replacement_id": None,
                "reason": f"{dep_id} is missing from current state",
            }
        if item.get("status") == "active":
            return {
                "dependency_id": dep_id,
                "registry": "instructions",
                "status": "active",
                "action": "retain_and_recheck",
                "replacement_id": dep_id,
                "reason": "Instruction remains active; if its content changed in place, re-evaluate the decision.",
            }
        replacement, chain, error = follow_supersession(dep_id, instructions)
        return {
            "dependency_id": dep_id,
            "registry": "instructions",
            "status": item.get("status"),
            "action": "candidate_replacement" if replacement and replacement != dep_id else "block",
            "replacement_id": replacement if replacement != dep_id else None,
            "lineage": chain,
            "reason": (
                f"Candidate active instruction is {replacement}; replacement is not automatic validation."
                if replacement and replacement != dep_id
                else error or "No active replacement found."
            ),
        }

    return {
        "dependency_id": dep_id,
        "registry": "unknown",
        "status": "unknown",
        "action": "block",
        "replacement_id": None,
        "reason": "Unrecognized dependency prefix.",
    }


def build_plan(state: dict[str, Any]) -> dict[str, Any]:
    facts = by_id(state.get("facts", []))
    assumptions = by_id(state.get("assumptions", []))
    instructions = by_id(state.get("instructions", []))

    entries: list[dict[str, Any]] = []
    for decision in state.get("decisions", []):
        if not isinstance(decision, dict) or decision.get("status") != "needs_review":
            continue
        did = str(decision.get("id"))
        triggers = [str(x) for x in (decision.get("review_triggered_by") or [])]
        dep_ids = list(dict.fromkeys(
            [str(x) for x in (decision.get("facts_used") or [])]
            + [str(x) for x in (decision.get("assumptions_used") or [])]
            + [str(x) for x in (decision.get("instructions_used") or [])]
        ))
        analyses = [dependency_analysis(x, facts, assumptions, instructions) for x in dep_ids]
        blockers = [x["dependency_id"] for x in analyses if x["action"] == "block"]
        migrations = [
            {
                "from": x["dependency_id"],
                "to": x.get("replacement_id"),
                "from_registry": x["registry"],
                "to_registry": x.get("replacement_registry", x["registry"]),
                "kind": x["action"],
            }
            for x in analyses
            if x.get("replacement_id") and x.get("replacement_id") != x["dependency_id"]
        ]
        entries.append({
            "decision_id": did,
            "decision": decision.get("decision", ""),
            "rationale": decision.get("rationale", ""),
            "review_reason": decision.get("review_reason", ""),
            "triggers": triggers,
            "current_dependencies": {
                "facts_used": list(decision.get("facts_used") or []),
                "assumptions_used": list(decision.get("assumptions_used") or []),
                "instructions_used": list(decision.get("instructions_used") or []),
            },
            "dependency_analysis": analyses,
            "candidate_migrations": migrations,
            "blockers": blockers,
            "semantic_review_required": True,
            "allowed_outcomes": ["revalidated", "superseded", "reversed", "blocked"],
            "guidance": (
                "A successor dependency is only a candidate migration. Re-evaluate the conclusion under current state; "
                "do not reactivate the decision merely because replacements exist."
            ),
        })

    return {
        "version": "1.0",
        "project": copy.deepcopy(state.get("project", {})),
        "source_state_version": state.get("version"),
        "decision_count": len(entries),
        "entries": entries,
    }


def validate_dependencies(state: dict[str, Any], decision: dict[str, Any]) -> None:
    facts = by_id(state.get("facts", []))
    assumptions = by_id(state.get("assumptions", []))
    instructions = by_id(state.get("instructions", []))

    for fid in decision.get("facts_used", []) or []:
        item = facts.get(str(fid))
        if not item or item.get("status") != "active":
            raise ValueError(f"{decision.get('id')}: fact dependency {fid} is not active")
    for aid in decision.get("assumptions_used", []) or []:
        item = assumptions.get(str(aid))
        if not item or item.get("status") != "active":
            raise ValueError(f"{decision.get('id')}: assumption dependency {aid} is not active")
    for iid in decision.get("instructions_used", []) or []:
        item = instructions.get(str(iid))
        if not item or item.get("status") != "active":
            raise ValueError(f"{decision.get('id')}: instruction dependency {iid} is not active")


def next_open_item_id(state: dict[str, Any]) -> str:
    numbers = []
    for item in state.get("open_items", []) or []:
        match = re.match(r"^O-(\d+)$", str(item.get("id", ""))) if isinstance(item, dict) else None
        if match:
            numbers.append(int(match.group(1)))
    return f"O-{(max(numbers) + 1 if numbers else 1):03d}"


def append_history(decision: dict[str, Any], entry: dict[str, Any]) -> None:
    history = decision.setdefault("validation_history", [])
    if not isinstance(history, list):
        raise ValueError(f"{decision.get('id')}: validation_history must be an array")
    history.append(entry)


def apply_resolutions(
    state: dict[str, Any],
    resolution_doc: dict[str, Any],
    *,
    timestamp: str | None = None,
) -> dict[str, Any]:
    out = copy.deepcopy(state)
    timestamp = timestamp or now_iso()
    decisions = by_id(out.get("decisions", []))
    resolutions = resolution_doc.get("resolutions", [])
    if not isinstance(resolutions, list):
        raise ValueError("resolution document: resolutions must be an array")

    seen: set[str] = set()
    for resolution in resolutions:
        if not isinstance(resolution, dict):
            raise ValueError("resolution entries must be objects")
        did = str(resolution.get("decision_id", ""))
        if not did or did in seen:
            raise ValueError(f"duplicate or missing decision_id in resolution: {did!r}")
        seen.add(did)
        decision = decisions.get(did)
        if not decision:
            raise ValueError(f"resolution references missing decision {did}")
        if decision.get("status") != "needs_review":
            raise ValueError(f"{did}: only needs_review decisions can be resolved (status={decision.get('status')})")

        outcome = resolution.get("outcome")
        if outcome not in {"revalidated", "superseded", "reversed", "blocked"}:
            raise ValueError(f"{did}: invalid outcome {outcome!r}")
        rationale = str(resolution.get("rationale", "")).strip()
        if not rationale:
            raise ValueError(f"{did}: resolution rationale is required")

        triggers = list(decision.get("review_triggered_by") or [])
        history_entry: dict[str, Any] = {
            "at": timestamp,
            "outcome": outcome,
            "triggers": triggers,
            "rationale": rationale,
        }

        if outcome == "revalidated":
            candidate = copy.deepcopy(decision)
            candidate["facts_used"] = list(resolution.get("facts_used", candidate.get("facts_used", [])) or [])
            candidate["assumptions_used"] = list(resolution.get("assumptions_used", candidate.get("assumptions_used", [])) or [])
            candidate["instructions_used"] = list(resolution.get("instructions_used", candidate.get("instructions_used", [])) or [])
            validate_dependencies(out, candidate)
            decision["facts_used"] = candidate["facts_used"]
            decision["assumptions_used"] = candidate["assumptions_used"]
            decision["instructions_used"] = candidate["instructions_used"]
            decision["status"] = "active"
            decision["last_validated_at"] = timestamp
            history_entry["dependencies_after"] = {
                "facts_used": candidate["facts_used"],
                "assumptions_used": candidate["assumptions_used"],
                "instructions_used": candidate["instructions_used"],
            }
            decision["review_triggered_by"] = []
            decision["review_reason"] = None
            append_history(decision, history_entry)

        elif outcome == "superseded":
            new_decision = copy.deepcopy(resolution.get("new_decision"))
            if not isinstance(new_decision, dict):
                raise ValueError(f"{did}: superseded outcome requires new_decision")
            new_id = str(new_decision.get("id", ""))
            if not DECISION_ID_RE.match(new_id):
                raise ValueError(f"{did}: new_decision.id must match D-###")
            if new_id in decisions:
                raise ValueError(f"{did}: replacement decision {new_id} already exists")
            for required in ("decision", "rationale"):
                if not str(new_decision.get(required, "")).strip():
                    raise ValueError(f"{did}: new_decision.{required} is required")
            new_decision.setdefault("facts_used", [])
            new_decision.setdefault("assumptions_used", [])
            new_decision.setdefault("instructions_used", [])
            new_decision["status"] = "active"
            new_decision.setdefault("superseded_by", None)
            new_decision["last_validated_at"] = timestamp
            new_decision.setdefault("validation_history", [])
            new_decision.setdefault("authority", "advisory")
            new_decision.setdefault("trust_level", "reviewed")
            new_decision.setdefault("origin", {"kind": "agent", "ref": "revalidation-workflow"})
            validate_dependencies(out, new_decision)

            decision["status"] = "superseded"
            decision["superseded_by"] = new_id
            decision["last_validated_at"] = timestamp
            history_entry["replacement_decision_id"] = new_id
            decision["review_triggered_by"] = []
            decision["review_reason"] = None
            append_history(decision, history_entry)
            out.setdefault("decisions", []).append(new_decision)
            decisions[new_id] = new_decision

        elif outcome == "reversed":
            decision["status"] = "reversed"
            decision["last_validated_at"] = timestamp
            decision["review_triggered_by"] = []
            decision["review_reason"] = None
            append_history(decision, history_entry)

        elif outcome == "blocked":
            decision["status"] = "needs_review"
            decision["review_reason"] = rationale
            append_history(decision, history_entry)
            if resolution.get("create_open_item", True):
                open_id = next_open_item_id(out)
                out.setdefault("open_items", []).append({
                    "id": open_id,
                    "type": "blocker",
                    "statement": f"Revalidation blocked for {did}: {rationale}",
                    "status": "open",
                    "owner": resolution.get("owner"),
                    "related_decision": did,
                    "created_at": timestamp,
                    "authority": "advisory",
                    "trust_level": "reviewed",
                    "origin": {"kind": "agent", "ref": "revalidation-workflow"},
                })
                history_entry["open_item_id"] = open_id

    out["version"] = "1.0"
    return out


def print_plan(plan: dict[str, Any]) -> None:
    print(f"Revalidation Plan: {plan['decision_count']} decision(s) require semantic review")
    for entry in plan["entries"]:
        print(f"\n- {entry['decision_id']}: {entry['decision']}")
        if entry["candidate_migrations"]:
            for migration in entry["candidate_migrations"]:
                print(f"  candidate: {migration['from']} -> {migration['to']} ({migration['kind']})")
        if entry["blockers"]:
            print(f"  blockers: {', '.join(entry['blockers'])}")
        print("  action: re-evaluate conclusion; choose revalidated / superseded / reversed / blocked")


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan and apply explicit decision revalidation")
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="Generate a revalidation plan from a governed state")
    p_plan.add_argument("state", type=Path)
    p_plan.add_argument("--output", type=Path, help="Write plan JSON to a file")
    p_plan.add_argument("--json", action="store_true", dest="as_json", help="Print plan JSON")
    p_plan.add_argument("--fail-if-empty", action="store_true", help="Exit 1 if there are no needs_review decisions")

    p_apply = sub.add_parser("apply", help="Apply an explicit revalidation resolution document")
    p_apply.add_argument("state", type=Path)
    p_apply.add_argument("resolution", type=Path)
    p_apply.add_argument("--output", type=Path, required=True, help="Write resolved state to this path")
    p_apply.add_argument("--at", dest="timestamp", help="Validation timestamp; useful for deterministic runs/tests")

    args = parser.parse_args()

    try:
        state = load_json(args.state)
        require_version(state, label="state")
        if args.command == "plan":
            plan = build_plan(state)
            if args.output:
                atomic_write_json(args.output, plan)
            if args.as_json:
                print(json.dumps(plan, ensure_ascii=False, indent=2))
            else:
                print_plan(plan)
            return 1 if args.fail_if_empty and not plan["entries"] else 0

        resolution = load_json(args.resolution)
        require_version(resolution, label="revalidation resolution")
        resolved = apply_resolutions(state, resolution, timestamp=args.timestamp)
        atomic_write_json(args.output, resolved)
        print(f"Applied {len(resolution.get('resolutions', []))} revalidation resolution(s) -> {args.output}")
        return 0

    except (OSError, json.JSONDecodeError, SafeIOError, ValueError) as exc:
        print(f"revalidate: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
