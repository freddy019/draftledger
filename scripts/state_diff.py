#!/usr/bin/env python3
"""State Diff + Dependency Revalidation for DraftLedger.

Compares two governed-state snapshots and identifies downstream decisions that
must be revalidated because facts, assumptions, or instructions changed.

Standard-library only.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

# Allow sibling imports both when executed and when imported by tests.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_io import SafeIOError, atomic_write_json, read_json as safe_read_json, require_version


@dataclass(frozen=True)
class Change:
    registry: str
    item_id: str
    change_type: str
    fields: tuple[str, ...]
    summary: str


@dataclass(frozen=True)
class Review:
    decision_id: str
    triggers: tuple[str, ...]
    reasons: tuple[str, ...]


REGISTRIES = {
    "facts": "F",
    "assumptions": "A",
    "instructions": "I",
    "decisions": "D",
    "open_items": "O",
}

# Fields that can change the meaning or validity of downstream reasoning.
MATERIAL_FIELDS = {
    "facts": {"statement", "status", "scope", "source", "superseded_by"},
    "assumptions": {
        "statement",
        "status",
        "confidence",
        "scope",
        "reason",
        "validation_condition",
        "promoted_to",
    },
    "instructions": {
        "instruction",
        "status",
        "scope",
        "scope_id",
        "priority",
        "key",
        "supersedes",
        "superseded_by",
        "expiry_condition",
    },
    "decisions": {
        "decision",
        "rationale",
        "status",
        "facts_used",
        "assumptions_used",
        "instructions_used",
        "superseded_by",
    },
    "open_items": {"type", "statement", "status", "owner"},
}


def load_state(path: Path) -> dict[str, Any]:
    return safe_read_json(path)


def by_id(items: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(x.get("id")): x for x in items if isinstance(x, dict) and x.get("id")}


def field_changes(before: dict[str, Any], after: dict[str, Any], allowed: set[str]) -> list[str]:
    fields = sorted(allowed | {"authority", "trust_level", "origin"} | ({"id"} if "id" in before or "id" in after else set()))
    return [f for f in fields if f != "id" and before.get(f) != after.get(f)]


def compute_changes(old: dict[str, Any], new: dict[str, Any]) -> list[Change]:
    changes: list[Change] = []
    for registry in REGISTRIES:
        old_items = by_id(old.get(registry, []) if isinstance(old.get(registry, []), list) else [])
        new_items = by_id(new.get(registry, []) if isinstance(new.get(registry, []), list) else [])
        ids = sorted(set(old_items) | set(new_items))
        for item_id in ids:
            if item_id not in old_items:
                changes.append(Change(registry, item_id, "added", tuple(), f"{item_id} added to {registry}"))
                continue
            if item_id not in new_items:
                changes.append(Change(registry, item_id, "removed", tuple(), f"{item_id} removed from {registry}"))
                continue
            fields = field_changes(old_items[item_id], new_items[item_id], MATERIAL_FIELDS[registry])
            if fields:
                changes.append(
                    Change(
                        registry,
                        item_id,
                        "modified",
                        tuple(fields),
                        f"{item_id} changed: {', '.join(fields)}",
                    )
                )
    return changes


def changed_upstream_ids(changes: list[Change]) -> set[str]:
    return {
        c.item_id
        for c in changes
        if c.registry in {"facts", "assumptions", "instructions"}
        and c.change_type in {"removed", "modified"}
    }


def dependency_revalidation(old: dict[str, Any], new: dict[str, Any], changes: list[Change]) -> list[Review]:
    upstream = changed_upstream_ids(changes)
    new_facts = by_id(new.get("facts", []))
    new_assumptions = by_id(new.get("assumptions", []))
    new_instructions = by_id(new.get("instructions", []))
    old_decisions = by_id(old.get("decisions", []))
    new_decisions = by_id(new.get("decisions", []))

    reviews: list[Review] = []
    for did, decision in sorted(new_decisions.items()):
        if decision.get("status") not in {"active", "needs_review"}:
            continue

        deps = set(decision.get("facts_used", []) or [])
        deps |= set(decision.get("assumptions_used", []) or [])
        deps |= set(decision.get("instructions_used", []) or [])
        triggers = sorted(deps & upstream)
        reasons: list[str] = []

        # Direct invalidation from changed dependencies.
        for dep in triggers:
            if dep.startswith("F-"):
                item = new_facts.get(dep)
                if item is None:
                    reasons.append(f"{dep} was removed")
                else:
                    reasons.append(f"{dep} changed (status={item.get('status')})")
            elif dep.startswith("A-"):
                item = new_assumptions.get(dep)
                if item is None:
                    reasons.append(f"{dep} was removed")
                else:
                    reasons.append(f"{dep} changed (status={item.get('status')})")
            elif dep.startswith("I-"):
                item = new_instructions.get(dep)
                if item is None:
                    reasons.append(f"{dep} was removed")
                else:
                    reasons.append(f"{dep} changed (status={item.get('status')})")

        # Catch decisions that are invalid in the new snapshot even if an upstream
        # dependency was already stale before the comparison.
        for fid in decision.get("facts_used", []) or []:
            item = new_facts.get(fid)
            if item is None or item.get("status") != "active":
                if fid not in triggers:
                    triggers.append(fid)
                reasons.append(f"{fid} is no longer an active fact")
        for aid in decision.get("assumptions_used", []) or []:
            item = new_assumptions.get(aid)
            if item is None or item.get("status") in {"rejected", "expired"}:
                if aid not in triggers:
                    triggers.append(aid)
                reasons.append(f"{aid} is not a valid supporting assumption")
        for iid in decision.get("instructions_used", []) or []:
            item = new_instructions.get(iid)
            if item is None or item.get("status") != "active":
                if iid not in triggers:
                    triggers.append(iid)
                reasons.append(f"{iid} is no longer an active instruction")

        # A decision changed itself: that is a direct review-worthy event unless
        # it was newly added or already explicitly marked.
        old_d = old_decisions.get(did)
        if old_d and decision.get("status") == "active":
            self_fields = field_changes(old_d, decision, MATERIAL_FIELDS["decisions"])
            if self_fields and any(f not in {"status"} for f in self_fields):
                reasons.append(f"decision definition changed: {', '.join(self_fields)}")

        if reasons:
            reviews.append(
                Review(
                    decision_id=did,
                    triggers=tuple(sorted(set(triggers))),
                    reasons=tuple(sorted(set(reasons))),
                )
            )

    return reviews


def annotate_review_state(state: dict[str, Any], reviews: list[Review]) -> dict[str, Any]:
    out = copy.deepcopy(state)
    review_map = {r.decision_id: r for r in reviews}
    for decision in out.get("decisions", []):
        if not isinstance(decision, dict):
            continue
        did = decision.get("id")
        review = review_map.get(did)
        if not review:
            continue
        if decision.get("status") == "active":
            decision["status"] = "needs_review"
        decision["review_triggered_by"] = list(review.triggers)
        decision["review_reason"] = "; ".join(review.reasons)
    return out


def print_text(changes: list[Change], reviews: list[Review]) -> None:
    print(f"State Diff: {len(changes)} material change(s), {len(reviews)} decision(s) need revalidation")
    if changes:
        print("\nChanges")
        for c in changes:
            print(f"- [{c.registry}] {c.summary}")
    if reviews:
        print("\nDependency revalidation")
        for r in reviews:
            trigger_text = ", ".join(r.triggers) if r.triggers else "decision itself"
            print(f"- {r.decision_id}: REVIEW (triggered by {trigger_text})")
            for reason in r.reasons:
                print(f"  - {reason}")
    else:
        print("\nDependency revalidation: no active decisions require review")


def main() -> int:
    parser = argparse.ArgumentParser(description="Diff DraftLedger snapshots and revalidate decision dependencies")
    parser.add_argument("before", type=Path, help="Previous governed state JSON")
    parser.add_argument("after", type=Path, help="Current governed state JSON")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit machine-readable report")
    parser.add_argument("--write-review-state", type=Path, help="Write a copy of AFTER with affected active decisions marked needs_review")
    parser.add_argument("--fail-on-review", action="store_true", help="Exit 1 when one or more decisions need revalidation")
    args = parser.parse_args()

    try:
        old = load_state(args.before)
        new = load_state(args.after)
        require_version(old, label="before state")
        require_version(new, label="after state")
        changes = compute_changes(old, new)
        reviews = dependency_revalidation(old, new, changes)
    except (OSError, json.JSONDecodeError, SafeIOError, ValueError) as exc:
        print(f"state-diff: {exc}", file=sys.stderr)
        return 2

    if args.write_review_state:
        annotated = annotate_review_state(new, reviews)
        atomic_write_json(args.write_review_state, annotated)

    if args.as_json:
        report = {
            "changes": [asdict(c) for c in changes],
            "reviews": [asdict(r) for r in reviews],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_text(changes, reviews)

    if args.fail_on_review and reviews:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
