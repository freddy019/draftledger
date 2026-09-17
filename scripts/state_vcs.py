#!/usr/bin/env python3
"""Append-only state version control for DraftLedger.

Provides checkpoints, branches, rollback, three-way merge, and ref-to-ref diff
for governed state snapshots. Standard-library only.

This is deliberately not a replacement for Git. It versions the *semantic task
state* so an agent can branch hypotheses and restore prior control-plane state
without treating lossy conversation history as the source of truth.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow sibling imports both when executed and when imported by tests.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_io import SafeIOError, advisory_lock, atomic_write_json, read_json as safe_read_json, require_version

from state_diff import (  # noqa: E402
    Review,
    annotate_review_state,
    compute_changes,
    dependency_revalidation,
)


FORMAT_VERSION = "1.0"
REGISTRIES = ("facts", "assumptions", "instructions", "decisions", "open_items")
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
CHECKPOINT_RE = re.compile(r"^C-[0-9a-f]{12}$")
_MISSING = object()


class StateVCSError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return safe_read_json(path)


def write_json(path: Path, value: Any) -> None:
    atomic_write_json(path, value)


def repo_meta_path(repo: Path) -> Path:
    return repo / "meta.json"


def checkpoint_path(repo: Path, checkpoint_id: str) -> Path:
    return repo / "checkpoints" / f"{checkpoint_id}.json"


def validate_branch_name(name: str) -> None:
    if not BRANCH_RE.match(name) or ".." in name or name.endswith("/") or "//" in name:
        raise StateVCSError(f"invalid branch name: {name!r}")


def load_meta(repo: Path) -> dict[str, Any]:
    path = repo_meta_path(repo)
    if not path.exists():
        raise StateVCSError(f"not an initialized state repository: {repo}")
    meta = read_json(path)
    if meta.get("format_version") != FORMAT_VERSION:
        raise StateVCSError(
            f"unsupported repository format {meta.get('format_version')!r}; expected {FORMAT_VERSION}"
        )
    if not isinstance(meta.get("branches"), dict):
        raise StateVCSError("repository metadata has no valid branches map")
    return meta


def save_meta(repo: Path, meta: dict[str, Any]) -> None:
    write_json(repo_meta_path(repo), meta)


def compute_checkpoint_id(payload_without_id: dict[str, Any]) -> str:
    return "C-" + sha256_hex(payload_without_id)[:12]


def create_checkpoint_record(
    state: dict[str, Any],
    *,
    parents: list[str],
    message: str,
    created_at: str,
    operation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "created_at": created_at,
        "message": message,
        "parents": list(parents),
        "state_hash": "sha256:" + sha256_hex(state),
        "state": copy.deepcopy(state),
    }
    if operation:
        payload["operation"] = copy.deepcopy(operation)
    checkpoint_id = compute_checkpoint_id(payload)
    return {"id": checkpoint_id, **payload}


def store_checkpoint(repo: Path, record: dict[str, Any]) -> None:
    cid = str(record.get("id", ""))
    if not CHECKPOINT_RE.match(cid):
        raise StateVCSError(f"invalid checkpoint id: {cid!r}")
    path = checkpoint_path(repo, cid)
    if path.exists():
        existing = read_json(path)
        if existing != record:
            raise StateVCSError(f"checkpoint hash collision or immutable checkpoint mismatch: {cid}")
        return
    write_json(path, record)


def load_checkpoint(repo: Path, checkpoint_id: str) -> dict[str, Any]:
    if not CHECKPOINT_RE.match(checkpoint_id):
        raise StateVCSError(f"invalid checkpoint id: {checkpoint_id!r}")
    path = checkpoint_path(repo, checkpoint_id)
    if not path.exists():
        raise StateVCSError(f"unknown checkpoint: {checkpoint_id}")
    record = read_json(path)
    payload = {k: copy.deepcopy(v) for k, v in record.items() if k != "id"}
    expected_id = compute_checkpoint_id(payload)
    if record.get("id") != expected_id or record.get("id") != checkpoint_id:
        raise StateVCSError(f"checkpoint integrity failure: {checkpoint_id} id mismatch")
    state = record.get("state")
    if not isinstance(state, dict):
        raise StateVCSError(f"checkpoint {checkpoint_id} has no valid state object")
    require_version(state, label="checkpoint state")
    expected_hash = "sha256:" + sha256_hex(state)
    if record.get("state_hash") != expected_hash:
        raise StateVCSError(f"checkpoint integrity failure: {checkpoint_id} state hash mismatch")
    return record


def resolve_ref(repo: Path, meta: dict[str, Any], ref: str) -> str:
    branches = meta.get("branches", {})
    if ref in branches:
        cid = branches[ref]
        if not isinstance(cid, str):
            raise StateVCSError(f"branch {ref!r} has invalid head")
        return cid
    if CHECKPOINT_RE.match(ref) and checkpoint_path(repo, ref).exists():
        return ref
    raise StateVCSError(f"unknown branch or checkpoint: {ref}")


def current_branch(meta: dict[str, Any]) -> str:
    branch = meta.get("current_branch")
    if not isinstance(branch, str) or not branch:
        raise StateVCSError("repository has no current branch")
    if branch not in meta.get("branches", {}):
        raise StateVCSError(f"current branch {branch!r} is missing")
    return branch


def head_id(meta: dict[str, Any]) -> str:
    branch = current_branch(meta)
    cid = meta["branches"].get(branch)
    if not isinstance(cid, str):
        raise StateVCSError(f"branch {branch!r} has invalid head")
    return cid


def init_repo(
    repo: Path,
    state: dict[str, Any],
    *,
    branch: str = "main",
    message: str = "initial state",
    created_at: str | None = None,
) -> str:
    require_version(state, label="state")
    validate_branch_name(branch)
    meta_path = repo_meta_path(repo)
    if meta_path.exists():
        raise StateVCSError(f"repository already initialized: {repo}")
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "checkpoints").mkdir(parents=True, exist_ok=True)
    record = create_checkpoint_record(
        state,
        parents=[],
        message=message,
        created_at=created_at or now_iso(),
        operation={"type": "init"},
    )
    store_checkpoint(repo, record)
    meta = {
        "format_version": FORMAT_VERSION,
        "current_branch": branch,
        "branches": {branch: record["id"]},
    }
    save_meta(repo, meta)
    return str(record["id"])


def checkpoint_state(
    repo: Path,
    state: dict[str, Any],
    *,
    message: str,
    created_at: str | None = None,
    operation: dict[str, Any] | None = None,
    extra_parents: list[str] | None = None,
) -> str:
    require_version(state, label="state")
    meta = load_meta(repo)
    branch = current_branch(meta)
    parents = [head_id(meta)]
    load_checkpoint(repo, parents[0])
    for parent in extra_parents or []:
        if parent not in parents:
            load_checkpoint(repo, parent)
            parents.append(parent)
    record = create_checkpoint_record(
        state,
        parents=parents,
        message=message,
        created_at=created_at or now_iso(),
        operation=operation or {"type": "checkpoint"},
    )
    store_checkpoint(repo, record)
    meta["branches"][branch] = record["id"]
    save_meta(repo, meta)
    return str(record["id"])


def create_branch(repo: Path, name: str, *, from_ref: str | None = None) -> str:
    validate_branch_name(name)
    meta = load_meta(repo)
    if name in meta["branches"]:
        raise StateVCSError(f"branch already exists: {name}")
    source = resolve_ref(repo, meta, from_ref) if from_ref else head_id(meta)
    load_checkpoint(repo, source)
    meta["branches"][name] = source
    save_meta(repo, meta)
    return source


def switch_branch(repo: Path, name: str) -> dict[str, Any]:
    meta = load_meta(repo)
    if name not in meta["branches"]:
        raise StateVCSError(f"unknown branch: {name}")
    record = load_checkpoint(repo, str(meta["branches"][name]))
    meta["current_branch"] = name
    save_meta(repo, meta)
    return copy.deepcopy(record["state"])


def restore_ref(repo: Path, ref: str) -> dict[str, Any]:
    meta = load_meta(repo)
    cid = resolve_ref(repo, meta, ref)
    return copy.deepcopy(load_checkpoint(repo, cid)["state"])


def rollback_to(
    repo: Path,
    ref: str,
    *,
    message: str | None = None,
    created_at: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Append a rollback checkpoint; never rewrites or deletes history."""
    meta = load_meta(repo)
    target_id = resolve_ref(repo, meta, ref)
    target_state = copy.deepcopy(load_checkpoint(repo, target_id)["state"])
    cid = checkpoint_state(
        repo,
        target_state,
        message=message or f"rollback to {ref} ({target_id})",
        created_at=created_at,
        operation={"type": "rollback", "target": target_id},
    )
    return cid, target_state


def parent_ids(repo: Path, checkpoint_id: str) -> list[str]:
    record = load_checkpoint(repo, checkpoint_id)
    parents = record.get("parents", [])
    if not isinstance(parents, list) or not all(isinstance(x, str) for x in parents):
        raise StateVCSError(f"checkpoint {checkpoint_id} has invalid parent list")
    return list(parents)


def ancestor_distances(repo: Path, checkpoint_id: str) -> dict[str, int]:
    distances: dict[str, int] = {checkpoint_id: 0}
    queue: deque[str] = deque([checkpoint_id])
    while queue:
        current = queue.popleft()
        distance = distances[current]
        for parent in parent_ids(repo, current):
            if parent not in distances or distance + 1 < distances[parent]:
                distances[parent] = distance + 1
                queue.append(parent)
    return distances


def find_merge_base(repo: Path, ours: str, theirs: str) -> str:
    a = ancestor_distances(repo, ours)
    b = ancestor_distances(repo, theirs)
    common = set(a) & set(b)
    if not common:
        raise StateVCSError(f"no common ancestor between {ours} and {theirs}")
    # A common ancestor that is itself an ancestor of another common ancestor
    # is not a merge base, even if shortcut merge edges make it nearer.
    older = set()
    for cid in common:
        older.update(set(ancestor_distances(repo, cid)) - {cid})
    bases = common - older
    if len(bases) != 1:
        raise StateVCSError("ambiguous merge base; reconcile criss-cross history explicitly")
    return next(iter(bases))


def _json_for_conflict(value: Any) -> Any:
    return None if value is _MISSING else copy.deepcopy(value)


def merge_value(base: Any, ours: Any, theirs: Any, path: str, conflicts: list[dict[str, Any]]) -> Any:
    if ours is not _MISSING and theirs is not _MISSING and ours == theirs:
        return copy.deepcopy(ours)
    if base is not _MISSING and ours == base:
        return copy.deepcopy(theirs) if theirs is not _MISSING else _MISSING
    if base is not _MISSING and theirs == base:
        return copy.deepcopy(ours) if ours is not _MISSING else _MISSING
    if base is _MISSING:
        if ours is _MISSING:
            return copy.deepcopy(theirs)
        if theirs is _MISSING:
            return copy.deepcopy(ours)
    else:
        if ours is _MISSING and theirs is _MISSING:
            return _MISSING
        # One side deleted while the other side independently changed.
        if ours is _MISSING or theirs is _MISSING:
            conflicts.append({
                "path": path,
                "kind": "delete/modify",
                "base": _json_for_conflict(base),
                "ours": _json_for_conflict(ours),
                "theirs": _json_for_conflict(theirs),
            })
            return copy.deepcopy(theirs if ours is _MISSING else ours)

    if all(isinstance(x, dict) for x in (base, ours, theirs) if x is not _MISSING):
        base_dict = {} if base is _MISSING else base
        ours_dict = {} if ours is _MISSING else ours
        theirs_dict = {} if theirs is _MISSING else theirs
        result: dict[str, Any] = {}
        keys = sorted(set(base_dict) | set(ours_dict) | set(theirs_dict))
        for key in keys:
            value = merge_value(
                base_dict.get(key, _MISSING),
                ours_dict.get(key, _MISSING),
                theirs_dict.get(key, _MISSING),
                f"{path}/{key}" if path else key,
                conflicts,
            )
            if value is not _MISSING:
                result[key] = value
        return result

    conflicts.append({
        "path": path,
        "kind": "content",
        "base": _json_for_conflict(base),
        "ours": _json_for_conflict(ours),
        "theirs": _json_for_conflict(theirs),
    })
    return copy.deepcopy(ours) if ours is not _MISSING else _MISSING


def registry_map(items: Any, registry: str) -> dict[str, dict[str, Any]]:
    if items is _MISSING:
        return {}
    if not isinstance(items, list):
        raise StateVCSError(f"{registry}: expected an array")
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            raise StateVCSError(f"{registry}: every item must be an object with id")
        item_id = str(item["id"])
        if item_id in result:
            raise StateVCSError(f"{registry}: duplicate id {item_id}")
        result[item_id] = item
    return result


def merge_registry(base: Any, ours: Any, theirs: Any, registry: str, conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    b = registry_map(base, registry)
    o = registry_map(ours, registry)
    t = registry_map(theirs, registry)
    merged: list[dict[str, Any]] = []
    for item_id in sorted(set(b) | set(o) | set(t)):
        value = merge_value(
            b.get(item_id, _MISSING),
            o.get(item_id, _MISSING),
            t.get(item_id, _MISSING),
            f"{registry}/{item_id}",
            conflicts,
        )
        if value is not _MISSING:
            if not isinstance(value, dict):
                raise StateVCSError(f"{registry}/{item_id}: merge produced non-object")
            merged.append(value)
    return merged


def merge_states(
    base: dict[str, Any], ours: dict[str, Any], theirs: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    conflicts: list[dict[str, Any]] = []
    merged: dict[str, Any] = {}
    keys = sorted(set(base) | set(ours) | set(theirs))
    for key in keys:
        if key in REGISTRIES:
            merged[key] = merge_registry(
                base.get(key, _MISSING), ours.get(key, _MISSING), theirs.get(key, _MISSING), key, conflicts
            )
            continue
        value = merge_value(
            base.get(key, _MISSING),
            ours.get(key, _MISSING),
            theirs.get(key, _MISSING),
            key,
            conflicts,
        )
        if value is not _MISSING:
            merged[key] = value
    return merged, conflicts


def merge_ref(
    repo: Path,
    source_ref: str,
    *,
    message: str | None = None,
    created_at: str | None = None,
) -> tuple[str | None, dict[str, Any] | None, dict[str, Any]]:
    meta = load_meta(repo)
    branch = current_branch(meta)
    ours_id = head_id(meta)
    theirs_id = resolve_ref(repo, meta, source_ref)
    if ours_id == theirs_id:
        state = copy.deepcopy(load_checkpoint(repo, ours_id)["state"])
        return None, state, {
            "status": "already-up-to-date",
            "current_branch": branch,
            "ours": ours_id,
            "theirs": theirs_id,
            "merge_base": ours_id,
            "conflicts": [],
            "reviews": [],
        }

    base_id = find_merge_base(repo, ours_id, theirs_id)
    base_state = copy.deepcopy(load_checkpoint(repo, base_id)["state"])
    ours_state = copy.deepcopy(load_checkpoint(repo, ours_id)["state"])
    theirs_state = copy.deepcopy(load_checkpoint(repo, theirs_id)["state"])

    merged, conflicts = merge_states(base_state, ours_state, theirs_state)
    if conflicts:
        return None, None, {
            "status": "conflict",
            "current_branch": branch,
            "ours": ours_id,
            "theirs": theirs_id,
            "merge_base": base_id,
            "conflicts": conflicts,
            "reviews": [],
        }

    # Merging can import a changed premise into an otherwise valid branch. Mark
    # affected decisions instead of silently trusting old conclusions.
    changes = compute_changes(ours_state, merged)
    reviews = dependency_revalidation(ours_state, merged, changes)
    incoming_reviews = dependency_revalidation(theirs_state, merged, compute_changes(theirs_state, merged))
    combined = {}
    for review in reviews + incoming_reviews:
        prior = combined.get(review.decision_id)
        combined[review.decision_id] = Review(
            review.decision_id,
            tuple(sorted(set(review.triggers) | (set(prior.triggers) if prior else set()))),
            tuple(sorted(set(review.reasons) | (set(prior.reasons) if prior else set()))),
        )
    reviews = [combined[key] for key in sorted(combined)]
    merged = annotate_review_state(merged, reviews)

    record = create_checkpoint_record(
        merged,
        parents=[ours_id, theirs_id],
        message=message or f"merge {source_ref} into {branch}",
        created_at=created_at or now_iso(),
        operation={"type": "merge", "source": source_ref, "source_checkpoint": theirs_id, "merge_base": base_id},
    )
    store_checkpoint(repo, record)
    meta["branches"][branch] = record["id"]
    save_meta(repo, meta)
    report = {
        "status": "merged",
        "current_branch": branch,
        "checkpoint": record["id"],
        "ours": ours_id,
        "theirs": theirs_id,
        "merge_base": base_id,
        "conflicts": [],
        "reviews": [
            {
                "decision_id": r.decision_id,
                "triggers": list(r.triggers),
                "reasons": list(r.reasons),
            }
            for r in reviews
        ],
    }
    return str(record["id"]), merged, report


def diff_refs(repo: Path, left_ref: str, right_ref: str) -> dict[str, Any]:
    meta = load_meta(repo)
    left_id = resolve_ref(repo, meta, left_ref)
    right_id = resolve_ref(repo, meta, right_ref)
    left = load_checkpoint(repo, left_id)["state"]
    right = load_checkpoint(repo, right_id)["state"]
    changes = compute_changes(left, right)
    reviews = dependency_revalidation(left, right, changes)
    return {
        "left": left_id,
        "right": right_id,
        "changes": [
            {
                "registry": c.registry,
                "item_id": c.item_id,
                "change_type": c.change_type,
                "fields": list(c.fields),
                "summary": c.summary,
            }
            for c in changes
        ],
        "reviews": [
            {
                "decision_id": r.decision_id,
                "triggers": list(r.triggers),
                "reasons": list(r.reasons),
            }
            for r in reviews
        ],
    }


def log_records(repo: Path, start_ref: str | None = None, max_count: int = 20) -> list[dict[str, Any]]:
    meta = load_meta(repo)
    cid = resolve_ref(repo, meta, start_ref) if start_ref else head_id(meta)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    while cid and cid not in seen and len(out) < max_count:
        seen.add(cid)
        record = load_checkpoint(repo, cid)
        out.append({
            "id": cid,
            "created_at": record.get("created_at"),
            "message": record.get("message"),
            "parents": list(record.get("parents") or []),
            "operation": copy.deepcopy(record.get("operation")),
            "state_hash": record.get("state_hash"),
        })
        parents = record.get("parents") or []
        cid = str(parents[0]) if parents else ""
    return out


def print_diff(report: dict[str, Any]) -> None:
    print(f"State VCS diff: {report['left']} -> {report['right']}")
    print(f"{len(report['changes'])} material change(s), {len(report['reviews'])} decision(s) need review")
    for change in report["changes"]:
        print(f"- [{change['registry']}] {change['summary']}")
    if report["reviews"]:
        print("\nDependency revalidation")
        for review in report["reviews"]:
            triggers = ", ".join(review["triggers"]) or "decision itself"
            print(f"- {review['decision_id']}: REVIEW (triggered by {triggers})")


def main() -> int:
    parser = argparse.ArgumentParser(description="Version governed task state with checkpoints, branches, rollback, and merge")
    parser.add_argument("--repo", type=Path, default=Path(".agent-state/vcs"), help="State VCS directory")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize a state repository and create the first checkpoint")
    p_init.add_argument("state", type=Path)
    p_init.add_argument("--branch", default="main")
    p_init.add_argument("-m", "--message", default="initial state")
    p_init.add_argument("--at", dest="created_at")

    p_cp = sub.add_parser("checkpoint", help="Append a checkpoint to the current branch")
    p_cp.add_argument("state", type=Path)
    p_cp.add_argument("-m", "--message", required=True)
    p_cp.add_argument("--at", dest="created_at")

    p_branch = sub.add_parser("branch", help="Create a branch at the current head or another ref")
    p_branch.add_argument("name")
    p_branch.add_argument("--from", dest="from_ref")

    p_switch = sub.add_parser("switch", help="Switch current branch and optionally materialize its state")
    p_switch.add_argument("name")
    p_switch.add_argument("--output", type=Path)

    p_restore = sub.add_parser("restore", help="Materialize a branch/checkpoint state without moving refs")
    p_restore.add_argument("ref")
    p_restore.add_argument("--output", type=Path, required=True)

    p_diff = sub.add_parser("diff", help="Diff two branches/checkpoints")
    p_diff.add_argument("left")
    p_diff.add_argument("right")
    p_diff.add_argument("--json", action="store_true", dest="as_json")

    p_rollback = sub.add_parser("rollback", help="Append a new checkpoint that restores a prior ref")
    p_rollback.add_argument("ref")
    p_rollback.add_argument("--output", type=Path)
    p_rollback.add_argument("-m", "--message")
    p_rollback.add_argument("--at", dest="created_at")

    p_merge = sub.add_parser("merge", help="Three-way merge a branch/checkpoint into the current branch")
    p_merge.add_argument("source")
    p_merge.add_argument("--output", type=Path)
    p_merge.add_argument("--conflicts", type=Path)
    p_merge.add_argument("-m", "--message")
    p_merge.add_argument("--at", dest="created_at")
    p_merge.add_argument("--json", action="store_true", dest="as_json")

    p_log = sub.add_parser("log", help="Show first-parent checkpoint history")
    p_log.add_argument("ref", nargs="?")
    p_log.add_argument("-n", "--max-count", type=int, default=20)
    p_log.add_argument("--json", action="store_true", dest="as_json")

    p_status = sub.add_parser("status", help="Compare a working state file with the current branch head")
    p_status.add_argument("state", type=Path)
    p_status.add_argument("--json", action="store_true", dest="as_json")

    args = parser.parse_args()
    repo: Path = args.repo

    try:
        if args.command == "init":
            state = read_json(args.state)
            with advisory_lock(repo / ".lock"):
                cid = init_repo(repo, state, branch=args.branch, message=args.message, created_at=args.created_at)
            print(f"Initialized {repo} on branch {args.branch} at {cid}")
            return 0

        if args.command == "checkpoint":
            state = read_json(args.state)
            with advisory_lock(repo / ".lock"):
                cid = checkpoint_state(repo, state, message=args.message, created_at=args.created_at)
            print(cid)
            return 0

        if args.command == "branch":
            with advisory_lock(repo / ".lock"):
                cid = create_branch(repo, args.name, from_ref=args.from_ref)
            print(f"Created branch {args.name} at {cid}")
            return 0

        if args.command == "switch":
            with advisory_lock(repo / ".lock"):
                state = switch_branch(repo, args.name)
            if args.output:
                write_json(args.output, state)
            print(f"Switched to {args.name}")
            return 0

        if args.command == "restore":
            state = restore_ref(repo, args.ref)
            write_json(args.output, state)
            print(f"Restored {args.ref} -> {args.output}")
            return 0

        if args.command == "diff":
            report = diff_refs(repo, args.left, args.right)
            if args.as_json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                print_diff(report)
            return 0

        if args.command == "rollback":
            with advisory_lock(repo / ".lock"):
                cid, state = rollback_to(repo, args.ref, message=args.message, created_at=args.created_at)
            if args.output:
                write_json(args.output, state)
            print(cid)
            return 0

        if args.command == "merge":
            with advisory_lock(repo / ".lock"):
                cid, state, report = merge_ref(repo, args.source, message=args.message, created_at=args.created_at)
            if report["status"] == "conflict":
                if args.conflicts:
                    write_json(args.conflicts, report)
                if args.as_json:
                    print(json.dumps(report, ensure_ascii=False, indent=2))
                else:
                    print(f"Merge conflict: {len(report['conflicts'])} conflict(s)")
                    for c in report["conflicts"]:
                        print(f"- {c['path']}: {c['kind']}")
                return 1
            if state is not None and args.output:
                write_json(args.output, state)
            if args.as_json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            elif report["status"] == "already-up-to-date":
                print("Already up to date")
            else:
                print(f"Merged into {report['current_branch']} at {cid}; {len(report['reviews'])} decision(s) marked for review")
            return 0

        if args.command == "log":
            records = log_records(repo, args.ref, max_count=max(args.max_count, 1))
            if args.as_json:
                print(json.dumps(records, ensure_ascii=False, indent=2))
            else:
                for rec in records:
                    parents = " ".join(rec["parents"]) if rec["parents"] else "-"
                    print(f"{rec['id']}  {rec['created_at']}  parents={parents}\n    {rec['message']}")
            return 0

        if args.command == "status":
            meta = load_meta(repo)
            hid = head_id(meta)
            head_state = load_checkpoint(repo, hid)["state"]
            working = read_json(args.state)
            require_version(working, label="working state")
            changes = compute_changes(head_state, working)
            exact_clean = head_state == working
            result = {
                "branch": current_branch(meta),
                "head": hid,
                "clean": exact_clean,
                "material_changes": [c.summary for c in changes],
                "state_hash_changed": not exact_clean,
            }
            if args.as_json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(f"On branch {result['branch']} at {hid}")
                if result["clean"]:
                    print("Working state is clean")
                else:
                    if changes:
                        print(f"Working state has {len(changes)} material governed-state change(s)")
                        for c in changes:
                            print(f"- {c.summary}")
                    else:
                        print("Working state differs only outside the governed registries")
            return 0

        raise StateVCSError(f"unsupported command: {args.command}")

    except (OSError, json.JSONDecodeError, SafeIOError, StateVCSError) as exc:
        print(f"state-vcs: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
