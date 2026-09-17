#!/usr/bin/env python3
"""Concurrent handoff board for multi-thread and multi-agent work.

The board is coordination data, not a source of instruction authority. Mutating
commands use an advisory lock, optimistic revisions, and atomic replacement.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_io import SafeIOError, advisory_lock, atomic_write_json, read_json, require_version


PROTOCOL_VERSION = "1.0"
AGENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
WORK_RE = re.compile(r"^W-[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
HANDOFF_RE = re.compile(r"^H-[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
WORK_STATUSES = {"ready", "claimed", "blocked", "completed", "cancelled"}
AGENT_STATUSES = {"active", "inactive"}


class HandoffError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HandoffError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise HandoffError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def state_fingerprint(path: Path) -> str:
    state = read_json(path)
    require_version(state, label="state")
    return "sha256:" + hashlib.sha256(canonical_bytes(state)).hexdigest()


def lock_path(board_path: Path) -> Path:
    return board_path.with_name(f".{board_path.name}.lock")


def agent_map(board: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in board.get("agents", []) if isinstance(item, dict)}


def work_map(board: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in board.get("work_items", []) if isinstance(item, dict)}


def scopes_overlap(left: str, right: str) -> bool:
    a = left.replace("\\", "/").strip().rstrip("/")
    b = right.replace("\\", "/").strip().rstrip("/")
    return bool(a and b and (a == b or a.startswith(b + "/") or b.startswith(a + "/")))


def event(board: dict[str, Any], *, at: str, event_type: str, actor: str, work_id: str | None = None,
          details: dict[str, Any] | None = None) -> None:
    events = board.setdefault("events", [])
    if not isinstance(events, list):
        raise HandoffError("events must be an array")
    row: dict[str, Any] = {
        "id": f"E-{len(events) + 1:06d}",
        "at": at,
        "type": event_type,
        "actor": actor,
        "details": copy.deepcopy(details or {}),
    }
    if work_id:
        row["work_item_id"] = work_id
    events.append(row)


def create_board(*, handoff_id: str, project_name: str, objective: str, created_at: str,
                 state_path: Path | None = None) -> dict[str, Any]:
    if not HANDOFF_RE.fullmatch(handoff_id):
        raise HandoffError("handoff id must start with H- and contain only letters, digits, dot, underscore or hyphen")
    if not project_name.strip() or not objective.strip():
        raise HandoffError("project_name and objective are required")
    parse_time(created_at, label="created_at")
    board: dict[str, Any] = {
        "version": PROTOCOL_VERSION,
        "handoff_id": handoff_id,
        "revision": 0,
        "project": {"name": project_name, "objective": objective},
        "created_at": created_at,
        "updated_at": created_at,
        "coordination": {
            "content_plane": "data",
            "claim_policy": "single-owner-with-lease",
            "integration_policy": "explicit-review-before-merge",
        },
        "base_state": None,
        "agents": [],
        "work_items": [],
        "events": [],
    }
    if state_path is not None:
        board["base_state"] = {"path": str(state_path), "fingerprint": state_fingerprint(state_path)}
    event(board, at=created_at, event_type="board_initialized", actor="system")
    return board


def load_board(path: Path) -> dict[str, Any]:
    board = read_json(path)
    require_version(board, expected=PROTOCOL_VERSION, label="handoff board")
    return board


def add_finding(findings: list[dict[str, str]], severity: str, code: str, message: str) -> None:
    findings.append({"severity": severity, "code": code, "message": message})


def lint_board(board: dict[str, Any], *, state_path: Path | None = None) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if board.get("version") != PROTOCOL_VERSION:
        add_finding(findings, "ERROR", "VERSION", f"expected handoff version {PROTOCOL_VERSION!r}")
    if not HANDOFF_RE.fullmatch(str(board.get("handoff_id", ""))):
        add_finding(findings, "ERROR", "HANDOFF_ID", "invalid or missing handoff_id")
    revision = board.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        add_finding(findings, "ERROR", "REVISION", "revision must be a non-negative integer")
    project = board.get("project")
    if not isinstance(project, dict) or not str(project.get("name", "")).strip() or not str(project.get("objective", "")).strip():
        add_finding(findings, "ERROR", "PROJECT", "project.name and project.objective are required")
    for key in ("created_at", "updated_at"):
        try:
            parse_time(str(board.get(key, "")), label=key)
        except HandoffError as exc:
            add_finding(findings, "ERROR", "TIMESTAMP", str(exc))

    agents = board.get("agents")
    if not isinstance(agents, list):
        add_finding(findings, "ERROR", "AGENTS", "agents must be an array")
        agents = []
    agent_ids: set[str] = set()
    for row in agents:
        if not isinstance(row, dict):
            add_finding(findings, "ERROR", "AGENT", "agent entries must be objects")
            continue
        aid = str(row.get("id", ""))
        if not AGENT_RE.fullmatch(aid):
            add_finding(findings, "ERROR", "AGENT_ID", f"invalid agent id {aid!r}")
        if aid in agent_ids:
            add_finding(findings, "ERROR", "DUPLICATE_AGENT", f"duplicate agent id {aid}")
        agent_ids.add(aid)
        if row.get("status") not in AGENT_STATUSES:
            add_finding(findings, "ERROR", "AGENT_STATUS", f"{aid}: invalid agent status")

    items = board.get("work_items")
    if not isinstance(items, list):
        add_finding(findings, "ERROR", "WORK_ITEMS", "work_items must be an array")
        items = []
    items_by_id: dict[str, dict[str, Any]] = {}
    for row in items:
        if not isinstance(row, dict):
            add_finding(findings, "ERROR", "WORK_ITEM", "work item entries must be objects")
            continue
        wid = str(row.get("id", ""))
        if not WORK_RE.fullmatch(wid):
            add_finding(findings, "ERROR", "WORK_ID", f"invalid work item id {wid!r}")
        if wid in items_by_id:
            add_finding(findings, "ERROR", "DUPLICATE_WORK", f"duplicate work item id {wid}")
        items_by_id[wid] = row
        if not str(row.get("title", "")).strip() or not str(row.get("objective", "")).strip():
            add_finding(findings, "ERROR", "WORK_DESCRIPTION", f"{wid}: title and objective are required")
        status = row.get("status")
        owner = row.get("owner")
        lease = row.get("lease_expires_at")
        if status not in WORK_STATUSES:
            add_finding(findings, "ERROR", "WORK_STATUS", f"{wid}: invalid status {status!r}")
        if owner is not None and owner not in agent_ids:
            add_finding(findings, "ERROR", "UNKNOWN_OWNER", f"{wid}: owner {owner!r} is not registered")
        if status == "claimed" and not owner:
            add_finding(findings, "ERROR", "CLAIM_OWNER", f"{wid}: claimed work must have an owner")
        if status == "claimed" and not lease:
            add_finding(findings, "ERROR", "CLAIM_LEASE", f"{wid}: claimed work must have a lease")
        if status != "claimed" and lease is not None:
            add_finding(findings, "ERROR", "STALE_LEASE", f"{wid}: only claimed work may have a lease")
        if status == "ready" and owner is not None:
            add_finding(findings, "ERROR", "READY_OWNER", f"{wid}: ready work cannot have an owner")
        if status == "blocked" and not owner:
            add_finding(findings, "ERROR", "BLOCKED_OWNER", f"{wid}: blocked work must retain an owner")
        if status == "completed" and (not owner or not isinstance(row.get("completion"), dict)):
            add_finding(findings, "ERROR", "COMPLETION", f"{wid}: completed work requires owner and completion record")
        if status != "completed" and row.get("completion") is not None:
            add_finding(findings, "ERROR", "STALE_COMPLETION", f"{wid}: completion record requires completed status")
        if lease:
            try:
                parse_time(str(lease), label=f"{wid}.lease_expires_at")
            except HandoffError as exc:
                add_finding(findings, "ERROR", "LEASE_TIME", str(exc))
        for field in ("depends_on", "scope", "acceptance_criteria", "inputs", "outputs", "progress", "blockers"):
            if not isinstance(row.get(field), list):
                add_finding(findings, "ERROR", "WORK_ARRAY", f"{wid}.{field} must be an array")
        if isinstance(row.get("scope"), list) and not row["scope"]:
            add_finding(findings, "ERROR", "WORK_SCOPE", f"{wid}: at least one explicit scope is required")
        if isinstance(row.get("acceptance_criteria"), list) and not row["acceptance_criteria"]:
            add_finding(findings, "ERROR", "WORK_ACCEPTANCE", f"{wid}: at least one acceptance criterion is required")
        blockers = row.get("blockers", []) if isinstance(row.get("blockers"), list) else []
        open_blockers = [value for value in blockers if isinstance(value, dict) and value.get("status") == "open"]
        if status == "blocked" and not open_blockers:
            add_finding(findings, "ERROR", "MISSING_BLOCKER", f"{wid}: blocked work needs an open blocker")
        if status != "blocked" and open_blockers:
            add_finding(findings, "ERROR", "OPEN_BLOCKER_STATUS", f"{wid}: open blockers require blocked status")

    graph: dict[str, list[str]] = {}
    for wid, row in items_by_id.items():
        dependencies = [str(value) for value in row.get("depends_on", [])] if isinstance(row.get("depends_on"), list) else []
        if len(dependencies) != len(set(dependencies)):
            add_finding(findings, "ERROR", "DUPLICATE_DEPENDENCY", f"{wid} has duplicate dependencies")
        graph[wid] = dependencies
        for dependency in dependencies:
            if dependency == wid:
                add_finding(findings, "ERROR", "SELF_DEPENDENCY", f"{wid} depends on itself")
            elif dependency not in items_by_id:
                add_finding(findings, "ERROR", "UNKNOWN_DEPENDENCY", f"{wid} depends on missing {dependency}")

    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(wid: str, trail: list[str]) -> None:
        if wid in visiting:
            cycle = trail[trail.index(wid):] + [wid]
            add_finding(findings, "ERROR", "DEPENDENCY_CYCLE", " -> ".join(cycle))
            return
        if wid in visited:
            return
        visiting.add(wid)
        for dependency in graph.get(wid, []):
            if dependency in graph:
                visit(dependency, trail + [dependency])
        visiting.remove(wid)
        visited.add(wid)
    for wid in graph:
        visit(wid, [wid])

    active = [row for row in items_by_id.values() if row.get("status") in {"claimed", "blocked"}]
    for index, left in enumerate(active):
        for right in active[index + 1:]:
            overlaps = sorted({a for a in left.get("scope", []) for b in right.get("scope", []) if scopes_overlap(str(a), str(b))})
            if overlaps:
                add_finding(findings, "ERROR", "SCOPE_COLLISION",
                            f"{left.get('id')} and {right.get('id')} have overlapping active scope: {', '.join(overlaps)}")

    events = board.get("events")
    if not isinstance(events, list):
        add_finding(findings, "ERROR", "EVENTS", "events must be an array")
    else:
        seen_events: set[str] = set()
        for index, row in enumerate(events, 1):
            if not isinstance(row, dict):
                add_finding(findings, "ERROR", "EVENT", "event entries must be objects")
                continue
            expected = f"E-{index:06d}"
            event_id = str(row.get("id", ""))
            if event_id != expected or event_id in seen_events:
                add_finding(findings, "ERROR", "EVENT_SEQUENCE", f"event {index} must be {expected}")
            seen_events.add(event_id)
            if row.get("work_item_id") is not None and row.get("work_item_id") not in items_by_id:
                add_finding(findings, "ERROR", "EVENT_WORK_REF", f"{event_id}: unknown work item")

    if state_path is not None:
        base = board.get("base_state")
        if not isinstance(base, dict) or not base.get("fingerprint"):
            add_finding(findings, "WARN", "NO_BASE_STATE", "board has no base state fingerprint")
        else:
            try:
                current = state_fingerprint(state_path)
                if current != base.get("fingerprint"):
                    add_finding(findings, "WARN", "STALE_BASE_STATE", "governed state differs from the handoff base snapshot")
            except (OSError, SafeIOError) as exc:
                add_finding(findings, "ERROR", "STATE_READ", str(exc))
    if isinstance(events, list):
        previous: datetime | None = None
        for index, row in enumerate(events, 1):
            if not isinstance(row, dict):
                continue
            try:
                current = parse_time(str(row.get("at", "")), label=f"event {index}.at")
                if previous is not None and current < previous:
                    add_finding(findings, "ERROR", "EVENT_TIME_ORDER", f"event {index} is older than the preceding event")
                previous = current
            except HandoffError as exc:
                add_finding(findings, "ERROR", "EVENT_TIME", str(exc))
    unique = {(row["severity"], row["code"], row["message"]): row for row in findings}
    return sorted(unique.values(), key=lambda row: (0 if row["severity"] == "ERROR" else 1, row["code"], row["message"]))


def assert_valid(board: dict[str, Any]) -> None:
    errors = [row for row in lint_board(board) if row["severity"] == "ERROR"]
    if errors:
        raise HandoffError("invalid handoff board: " + "; ".join(f"{row['code']}: {row['message']}" for row in errors[:5]))


def require_agent(board: dict[str, Any], agent_id: str) -> dict[str, Any]:
    agent = agent_map(board).get(agent_id)
    if not agent:
        raise HandoffError(f"agent is not registered: {agent_id}")
    if agent.get("status") != "active":
        raise HandoffError(f"agent is not active: {agent_id}")
    return agent


def require_work(board: dict[str, Any], work_id: str) -> dict[str, Any]:
    item = work_map(board).get(work_id)
    if not item:
        raise HandoffError(f"unknown work item: {work_id}")
    return item


def require_owner(item: dict[str, Any], agent_id: str) -> None:
    if item.get("owner") != agent_id:
        raise HandoffError(f"{item.get('id')}: owned by {item.get('owner')!r}, not {agent_id!r}")


def mutate(path: Path, expected_revision: int | None, at: str,
           operation: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    parse_time(at, label="at")
    with advisory_lock(lock_path(path)):
        board = load_board(path)
        assert_valid(board)
        if parse_time(at, label="at") < parse_time(str(board["updated_at"]), label="updated_at"):
            raise HandoffError("operation time cannot be earlier than the current board updated_at")
        if expected_revision is not None and board.get("revision") != expected_revision:
            raise HandoffError(f"stale board revision: expected {expected_revision}, current {board.get('revision')}")
        operation(board)
        board["revision"] = int(board["revision"]) + 1
        board["updated_at"] = at
        assert_valid(board)
        atomic_write_json(path, board)
    return board


def add_work(board: dict[str, Any], *, work_id: str, title: str, objective: str, dependencies: list[str],
             scope: list[str], acceptance: list[str], inputs: list[str], at: str) -> None:
    if not WORK_RE.fullmatch(work_id):
        raise HandoffError("work id must start with W- and contain only letters, digits, dot, underscore or hyphen")
    if not title.strip() or not objective.strip():
        raise HandoffError("work title and objective are required")
    if not scope or not all(value.strip() for value in scope):
        raise HandoffError("at least one non-empty scope is required")
    if not acceptance or not all(value.strip() for value in acceptance):
        raise HandoffError("at least one non-empty acceptance criterion is required")
    if work_id in work_map(board):
        raise HandoffError(f"work item already exists: {work_id}")
    existing = work_map(board)
    missing = [dependency for dependency in dependencies if dependency not in existing]
    if missing:
        raise HandoffError("unknown dependencies: " + ", ".join(missing))
    item = {
        "id": work_id,
        "title": title,
        "objective": objective,
        "status": "ready",
        "owner": None,
        "lease_expires_at": None,
        "depends_on": list(dict.fromkeys(dependencies)),
        "scope": list(dict.fromkeys(scope)),
        "acceptance_criteria": list(acceptance),
        "inputs": list(inputs),
        "outputs": [],
        "progress": [],
        "blockers": [],
        "created_at": at,
        "updated_at": at,
    }
    board["work_items"].append(item)
    event(board, at=at, event_type="work_added", actor="coordinator", work_id=work_id)


def register_agent(board: dict[str, Any], *, agent_id: str, thread_ref: str | None, at: str) -> None:
    if not AGENT_RE.fullmatch(agent_id):
        raise HandoffError("invalid agent id")
    agent = agent_map(board).get(agent_id)
    if agent:
        agent["thread_ref"] = thread_ref
        agent["status"] = "active"
        agent["last_seen_at"] = at
        event(board, at=at, event_type="agent_reactivated", actor=agent_id)
        return
    board["agents"].append({
        "id": agent_id,
        "thread_ref": thread_ref,
        "status": "active",
        "registered_at": at,
        "last_seen_at": at,
    })
    event(board, at=at, event_type="agent_registered", actor=agent_id)


def claim_work(board: dict[str, Any], *, work_id: str, agent_id: str, lease_minutes: int,
               take_over_expired: bool, at: str) -> None:
    if lease_minutes < 1 or lease_minutes > 10080:
        raise HandoffError("lease_minutes must be between 1 and 10080")
    agent = require_agent(board, agent_id)
    item = require_work(board, work_id)
    current = parse_time(at, label="at")
    if item.get("status") == "claimed":
        expires = parse_time(str(item.get("lease_expires_at")), label="lease_expires_at")
        if item.get("owner") == agent_id:
            event_type = "claim_renewed"
        elif expires <= current and take_over_expired:
            event_type = "expired_claim_taken_over"
        else:
            raise HandoffError(f"{work_id} is already claimed by {item.get('owner')}")
    elif item.get("status") == "ready":
        incomplete = [dependency for dependency in item.get("depends_on", [])
                      if work_map(board)[dependency].get("status") != "completed"]
        if incomplete:
            raise HandoffError(f"{work_id} has incomplete dependencies: {', '.join(incomplete)}")
        collisions = []
        for other in board.get("work_items", []):
            if other is item or other.get("status") not in {"claimed", "blocked"}:
                continue
            if any(scopes_overlap(str(a), str(b)) for a in item.get("scope", []) for b in other.get("scope", [])):
                collisions.append(str(other.get("id")))
        if collisions:
            raise HandoffError(f"{work_id} overlaps active work scope with: {', '.join(sorted(collisions))}")
        event_type = "work_claimed"
    else:
        raise HandoffError(f"{work_id} cannot be claimed from status {item.get('status')!r}")
    previous_owner = item.get("owner")
    item["status"] = "claimed"
    item["owner"] = agent_id
    item["lease_expires_at"] = (current + timedelta(minutes=lease_minutes)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    item["updated_at"] = at
    agent["last_seen_at"] = at
    details = {"lease_minutes": lease_minutes}
    if previous_owner and previous_owner != agent_id:
        details["previous_owner"] = previous_owner
    event(board, at=at, event_type=event_type, actor=agent_id, work_id=work_id, details=details)


def add_progress(board: dict[str, Any], *, work_id: str, agent_id: str, message: str,
                 artifacts: list[str], at: str) -> None:
    require_agent(board, agent_id)
    if not message.strip():
        raise HandoffError("progress message is required")
    item = require_work(board, work_id)
    require_owner(item, agent_id)
    if item.get("status") not in {"claimed", "blocked"}:
        raise HandoffError(f"{work_id}: progress requires claimed or blocked status")
    item["progress"].append({"at": at, "actor": agent_id, "message": message, "artifacts": list(artifacts)})
    item["updated_at"] = at
    agent_map(board)[agent_id]["last_seen_at"] = at
    event(board, at=at, event_type="progress_recorded", actor=agent_id, work_id=work_id)


def block_work(board: dict[str, Any], *, work_id: str, agent_id: str, reason: str, at: str) -> None:
    require_agent(board, agent_id)
    if not reason.strip():
        raise HandoffError("block reason is required")
    item = require_work(board, work_id)
    require_owner(item, agent_id)
    if item.get("status") != "claimed":
        raise HandoffError(f"{work_id}: only claimed work can be blocked")
    blocker_id = f"B-{len(item['blockers']) + 1:03d}"
    item["blockers"].append({"id": blocker_id, "status": "open", "reason": reason, "created_at": at})
    item["status"] = "blocked"
    item["lease_expires_at"] = None
    item["updated_at"] = at
    event(board, at=at, event_type="work_blocked", actor=agent_id, work_id=work_id,
          details={"blocker_id": blocker_id})


def resume_work(board: dict[str, Any], *, work_id: str, agent_id: str, resolution: str,
                take_over: bool, at: str) -> None:
    require_agent(board, agent_id)
    if not resolution.strip():
        raise HandoffError("blocker resolution is required")
    item = require_work(board, work_id)
    previous_owner = item.get("owner")
    if previous_owner != agent_id and not take_over:
        require_owner(item, agent_id)
    if item.get("status") != "blocked":
        raise HandoffError(f"{work_id}: only blocked work can be resumed")
    open_blockers = [row for row in item["blockers"] if row.get("status") == "open"]
    if not open_blockers:
        raise HandoffError(f"{work_id}: no open blocker")
    for blocker in open_blockers:
        blocker.update({"status": "resolved", "resolution": resolution, "resolved_at": at})
    item["status"] = "ready"
    item["owner"] = None
    item["updated_at"] = at
    details = {"resolution": resolution}
    if previous_owner != agent_id:
        details["previous_owner"] = previous_owner
    event(board, at=at, event_type="blocked_work_taken_over" if previous_owner != agent_id else "work_resumed",
          actor=agent_id, work_id=work_id, details=details)


def release_work(board: dict[str, Any], *, work_id: str, agent_id: str, reason: str, at: str) -> None:
    require_agent(board, agent_id)
    if not reason.strip():
        raise HandoffError("release reason is required")
    item = require_work(board, work_id)
    require_owner(item, agent_id)
    if item.get("status") != "claimed":
        raise HandoffError(f"{work_id}: only claimed work can be released")
    item["status"] = "ready"
    item["owner"] = None
    item["lease_expires_at"] = None
    item["updated_at"] = at
    event(board, at=at, event_type="claim_released", actor=agent_id, work_id=work_id,
          details={"reason": reason})


def complete_work(board: dict[str, Any], *, work_id: str, agent_id: str, summary: str,
                  outputs: list[str], at: str) -> None:
    require_agent(board, agent_id)
    if not summary.strip():
        raise HandoffError("completion summary is required")
    item = require_work(board, work_id)
    require_owner(item, agent_id)
    if item.get("status") != "claimed":
        raise HandoffError(f"{work_id}: only claimed work can be completed")
    item["status"] = "completed"
    item["lease_expires_at"] = None
    item["outputs"].extend({"path": output, "recorded_at": at, "actor": agent_id} for output in outputs)
    item["completion"] = {"at": at, "actor": agent_id, "summary": summary}
    item["updated_at"] = at
    event(board, at=at, event_type="work_completed", actor=agent_id, work_id=work_id,
          details={"summary": summary, "outputs": list(outputs)})


def cancel_work(board: dict[str, Any], *, work_id: str, agent_id: str, reason: str, at: str) -> None:
    require_agent(board, agent_id)
    if not reason.strip():
        raise HandoffError("cancellation reason is required")
    item = require_work(board, work_id)
    if item.get("status") in {"completed", "cancelled"}:
        raise HandoffError(f"{work_id}: cannot cancel from status {item.get('status')!r}")
    if item.get("owner") is not None:
        require_owner(item, agent_id)
    for blocker in item.get("blockers", []):
        if isinstance(blocker, dict) and blocker.get("status") == "open":
            blocker.update({"status": "resolved", "resolution": f"work cancelled: {reason}", "resolved_at": at})
    item["status"] = "cancelled"
    item["lease_expires_at"] = None
    item["updated_at"] = at
    event(board, at=at, event_type="work_cancelled", actor=agent_id, work_id=work_id,
          details={"reason": reason})


def refresh_state(board: dict[str, Any], *, state_path: Path, actor: str, at: str) -> None:
    active = [item["id"] for item in board.get("work_items", []) if item.get("status") in {"claimed", "blocked"}]
    if active:
        raise HandoffError("cannot refresh base state while work is claimed or blocked: " + ", ".join(active))
    board["base_state"] = {"path": str(state_path), "fingerprint": state_fingerprint(state_path)}
    event(board, at=at, event_type="base_state_refreshed", actor=actor,
          details={"path": str(state_path), "fingerprint": board["base_state"]["fingerprint"]})


def print_status(board: dict[str, Any]) -> None:
    counts = {status: 0 for status in sorted(WORK_STATUSES)}
    for item in board.get("work_items", []):
        counts[str(item.get("status"))] = counts.get(str(item.get("status")), 0) + 1
    print(f"Handoff {board.get('handoff_id')} revision {board.get('revision')}")
    print("Work: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    for item in board.get("work_items", []):
        owner = f" owner={item.get('owner')}" if item.get("owner") else ""
        print(f"- {item.get('id')} [{item.get('status')}]{owner}: {item.get('title')}")


def add_revision_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--expected-revision", type=int, help="Fail if another writer changed the board")
    parser.add_argument("--at", default=None, help="ISO-8601 event time; defaults to current UTC")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Coordinate multi-thread and multi-agent work through a governed handoff board")
    parser.add_argument("--board", type=Path, default=Path(".agent-state/handoff.json"))
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init")
    p_init.add_argument("--handoff-id", default="H-001")
    p_init.add_argument("--project-name", required=True)
    p_init.add_argument("--objective", required=True)
    p_init.add_argument("--state", type=Path)
    p_init.add_argument("--at", default=None)

    p_add = sub.add_parser("add")
    p_add.add_argument("work_id")
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--objective", required=True)
    p_add.add_argument("--depends-on", action="append", default=[])
    p_add.add_argument("--scope", action="append", required=True)
    p_add.add_argument("--accept", action="append", required=True)
    p_add.add_argument("--input", action="append", default=[])
    add_revision_arg(p_add)

    p_register = sub.add_parser("register")
    p_register.add_argument("agent_id")
    p_register.add_argument("--thread-ref")
    add_revision_arg(p_register)

    p_claim = sub.add_parser("claim")
    p_claim.add_argument("work_id")
    p_claim.add_argument("--agent", required=True)
    p_claim.add_argument("--lease-minutes", type=int, default=60)
    p_claim.add_argument("--take-over-expired", action="store_true")
    add_revision_arg(p_claim)

    p_progress = sub.add_parser("progress")
    p_progress.add_argument("work_id")
    p_progress.add_argument("--agent", required=True)
    p_progress.add_argument("--message", required=True)
    p_progress.add_argument("--artifact", action="append", default=[])
    add_revision_arg(p_progress)

    p_block = sub.add_parser("block")
    p_block.add_argument("work_id")
    p_block.add_argument("--agent", required=True)
    p_block.add_argument("--reason", required=True)
    add_revision_arg(p_block)

    p_resume = sub.add_parser("resume")
    p_resume.add_argument("work_id")
    p_resume.add_argument("--agent", required=True)
    p_resume.add_argument("--resolution", required=True)
    p_resume.add_argument("--take-over", action="store_true", help="Explicitly resolve work owned by another agent")
    add_revision_arg(p_resume)

    p_release = sub.add_parser("release")
    p_release.add_argument("work_id")
    p_release.add_argument("--agent", required=True)
    p_release.add_argument("--reason", required=True)
    add_revision_arg(p_release)

    p_complete = sub.add_parser("complete")
    p_complete.add_argument("work_id")
    p_complete.add_argument("--agent", required=True)
    p_complete.add_argument("--summary", required=True)
    p_complete.add_argument("--output", action="append", default=[])
    add_revision_arg(p_complete)

    p_cancel = sub.add_parser("cancel")
    p_cancel.add_argument("work_id")
    p_cancel.add_argument("--agent", required=True)
    p_cancel.add_argument("--reason", required=True)
    add_revision_arg(p_cancel)

    p_refresh = sub.add_parser("refresh-state")
    p_refresh.add_argument("state", type=Path)
    p_refresh.add_argument("--actor", required=True)
    add_revision_arg(p_refresh)

    p_status = sub.add_parser("status")
    p_status.add_argument("--json", action="store_true", dest="as_json")

    p_lint = sub.add_parser("lint")
    p_lint.add_argument("--state", type=Path)
    p_lint.add_argument("--strict", action="store_true")
    p_lint.add_argument("--json", action="store_true", dest="as_json")

    args = parser.parse_args(argv)
    path: Path = args.board
    try:
        if args.command == "init":
            at = args.at or now_iso()
            with advisory_lock(lock_path(path)):
                if path.exists():
                    raise HandoffError(f"handoff board already exists: {path}")
                board = create_board(handoff_id=args.handoff_id, project_name=args.project_name,
                                     objective=args.objective, created_at=at, state_path=args.state)
                assert_valid(board)
                atomic_write_json(path, board)
            print(f"Initialized {path} at revision 0")
            return 0

        if args.command == "status":
            board = load_board(path)
            assert_valid(board)
            if args.as_json:
                print(json.dumps(board, ensure_ascii=False, indent=2, allow_nan=False))
            else:
                print_status(board)
            return 0

        if args.command == "lint":
            board = load_board(path)
            findings = lint_board(board, state_path=args.state)
            if args.as_json:
                print(json.dumps({"findings": findings}, ensure_ascii=False, indent=2))
            else:
                for row in findings:
                    print(f"[{row['severity']}] {row['code']}: {row['message']}")
                errors = sum(row["severity"] == "ERROR" for row in findings)
                warnings = sum(row["severity"] == "WARN" for row in findings)
                print(f"Handoff lint: {errors} error(s), {warnings} warning(s)")
            has_error = any(row["severity"] == "ERROR" for row in findings)
            has_warning = any(row["severity"] == "WARN" for row in findings)
            return 1 if has_error or (args.strict and has_warning) else 0

        at = args.at or now_iso()
        operations: dict[str, Callable[[dict[str, Any]], None]] = {
            "add": lambda board: add_work(board, work_id=args.work_id, title=args.title, objective=args.objective,
                                             dependencies=args.depends_on, scope=args.scope,
                                             acceptance=args.accept, inputs=args.input, at=at),
            "register": lambda board: register_agent(board, agent_id=args.agent_id, thread_ref=args.thread_ref, at=at),
            "claim": lambda board: claim_work(board, work_id=args.work_id, agent_id=args.agent,
                                                 lease_minutes=args.lease_minutes,
                                                 take_over_expired=args.take_over_expired, at=at),
            "progress": lambda board: add_progress(board, work_id=args.work_id, agent_id=args.agent,
                                                      message=args.message, artifacts=args.artifact, at=at),
            "block": lambda board: block_work(board, work_id=args.work_id, agent_id=args.agent,
                                                 reason=args.reason, at=at),
            "resume": lambda board: resume_work(board, work_id=args.work_id, agent_id=args.agent,
                                                   resolution=args.resolution, take_over=args.take_over, at=at),
            "release": lambda board: release_work(board, work_id=args.work_id, agent_id=args.agent,
                                                     reason=args.reason, at=at),
            "complete": lambda board: complete_work(board, work_id=args.work_id, agent_id=args.agent,
                                                       summary=args.summary, outputs=args.output, at=at),
            "cancel": lambda board: cancel_work(board, work_id=args.work_id, agent_id=args.agent,
                                                   reason=args.reason, at=at),
            "refresh-state": lambda board: refresh_state(board, state_path=args.state, actor=args.actor, at=at),
        }
        board = mutate(path, args.expected_revision, at, operations[args.command])
        print(f"{args.command}: revision {board['revision']}")
        return 0
    except (OSError, SafeIOError, HandoffError, ValueError) as exc:
        print(f"handoff: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
