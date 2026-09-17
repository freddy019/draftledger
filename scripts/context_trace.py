#!/usr/bin/env python3
"""Context Provenance and Contamination Detection for DraftLedger.

This tool operates on *declared* reasoning context. It does not and cannot
introspect opaque platform/system prompts. Hosts or agents can generate a
context manifest that records which governed state items and summaries were
materially included in a reasoning step, then lint that manifest against the
current governed state.

Standard-library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Allow sibling imports both when executed and when imported by tests.
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from safe_io import SafeIOError, atomic_write_json, read_json as safe_read_json, require_version


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str


SEVERITY_ORDER = {"ERROR": 3, "WARN": 2, "INFO": 1}
REGISTRY_BY_PREFIX = {
    "F-": "facts",
    "A-": "assumptions",
    "I-": "instructions",
    "D-": "decisions",
    "O-": "open_items",
}
ACTIVE_STATUSES = {
    "facts": {"active"},
    "assumptions": {"active", "confirmed"},
    "instructions": {"active"},
    "decisions": {"active"},
    "open_items": {"open"},
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return safe_read_json(path)


def dump_json(data: dict[str, Any], path: Path | None) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    if path is None:
        sys.stdout.write(text)
    else:
        atomic_write_json(path, data)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def state_index(state: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    for registry in ("facts", "assumptions", "instructions", "decisions", "open_items"):
        items = state.get(registry, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                out[str(item["id"])] = (registry, item)
    return out


def registry_for_id(item_id: str) -> str | None:
    for prefix, registry in REGISTRY_BY_PREFIX.items():
        if item_id.startswith(prefix):
            return registry
    return None


def is_active(registry: str, item: dict[str, Any]) -> bool:
    return str(item.get("status")) in ACTIVE_STATUSES.get(registry, set())


def effective_authority(registry: str, item: dict[str, Any]) -> str:
    value = item.get("authority")
    if isinstance(value, str) and value:
        return value
    return "control" if registry == "instructions" else ("advisory" if registry in {"decisions", "open_items"} else "data")


def effective_trust(item: dict[str, Any]) -> str:
    value = item.get("trust_level")
    return str(value) if value else "unknown"


def origin_kind(item: dict[str, Any]) -> str:
    origin = item.get("origin")
    if isinstance(origin, dict) and origin.get("kind"):
        return str(origin["kind"])
    return "unknown"


def build_manifest(
    state: dict[str, Any],
    ids: Iterable[str] | None = None,
    *,
    created_at: str | None = None,
) -> dict[str, Any]:
    index = state_index(state)
    selected: list[str]
    requested = [str(x) for x in (ids or [])]
    if requested:
        missing = [x for x in requested if x not in index]
        if missing:
            raise ValueError("Unknown state IDs: " + ", ".join(missing))
        selected = requested
    else:
        selected = [item_id for item_id, (registry, item) in index.items() if is_active(registry, item)]

    entries: list[dict[str, Any]] = []
    for n, item_id in enumerate(selected, 1):
        registry, item = index[item_id]
        entries.append({
            "id": f"CXT-{n:03d}",
            "kind": "state",
            "source_id": item_id,
            "registry": registry,
            "snapshot_hash": digest(item),
            "included_via": "direct",
            "authority": effective_authority(registry, item),
            "trust_level": effective_trust(item),
            "origin_kind": origin_kind(item),
            "plane": "control" if registry == "instructions" else "data",
        })

    return {
        "version": "1.0",
        "project": {"name": state.get("project", {}).get("name", "")},
        "created_at": created_at or now_iso(),
        "state_fingerprint": digest(state),
        "context_entries": entries,
        "summaries": [],
        "notes": "Manifest records declared reasoning context; opaque host/system prompts are outside its visibility.",
    }


def add(findings: list[Finding], severity: str, code: str, message: str) -> None:
    findings.append(Finding(severity, code, message))


def summary_index(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    summaries = manifest.get("summaries", [])
    if not isinstance(summaries, list):
        return {}
    return {
        str(x.get("id")): x
        for x in summaries
        if isinstance(x, dict) and x.get("id")
    }


def active_instruction_successor(
    item: dict[str, Any], instructions: dict[str, dict[str, Any]]
) -> str | None:
    """Find an active instruction with the same mutable identity."""
    key = item.get("key")
    if not key:
        return None
    scope = item.get("scope")
    scope_id = item.get("scope_id")
    candidates = [
        iid for iid, candidate in instructions.items()
        if candidate.get("status") == "active"
        and candidate.get("key") == key
        and candidate.get("scope") == scope
        and candidate.get("scope_id") == scope_id
    ]
    return sorted(candidates)[0] if candidates else None


def lint_manifest(state: dict[str, Any], manifest: dict[str, Any]) -> list[Finding]:
    findings: list[Finding] = []
    index = state_index(state)
    instructions = {
        item_id: item for item_id, (registry, item) in index.items() if registry == "instructions"
    }
    summaries = summary_index(manifest)

    if manifest.get("state_fingerprint") != digest(state):
        add(
            findings,
            "INFO",
            "STATE_FINGERPRINT_MISMATCH",
            "The governed state changed after this context manifest was created. Item-level provenance checks were still performed.",
        )

    # Detect summary provenance cycles. Cyclic summaries are not a valid source
    # of truth because none of the nodes has an acyclic grounding path.
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit_summary(sid: str, trail: list[str]) -> None:
        if sid in visited:
            return
        if sid in visiting:
            try:
                start = trail.index(sid)
                cycle = trail[start:] + [sid]
            except ValueError:
                cycle = trail + [sid]
            add(findings, "ERROR", "SUMMARY_CYCLE", f"Summary provenance cycle: {' -> '.join(cycle)}")
            return
        visiting.add(sid)
        trail.append(sid)
        summary = summaries.get(sid, {})
        for dep in summary.get("derived_from", []) or []:
            dep_id = str(dep)
            if dep_id in summaries:
                visit_summary(dep_id, trail)
        trail.pop()
        visiting.remove(sid)
        visited.add(sid)

    for sid in summaries:
        visit_summary(sid, [])

    # First pass: determine whether summaries are tainted by missing/stale dependencies.
    tainted_summaries: dict[str, list[str]] = {}
    for sid, summary in summaries.items():
        deps = summary.get("derived_from", [])
        if not isinstance(deps, list) or not deps:
            add(findings, "WARN", "UNGROUNDED_SUMMARY", f"{sid} has no derived_from provenance")
            tainted_summaries.setdefault(sid, []).append("no provenance")
            continue
        for dep in deps:
            dep_id = str(dep)
            if dep_id in summaries:
                # Summary-to-summary taint is resolved in a propagation pass below.
                continue
            record = index.get(dep_id)
            if record is None:
                add(findings, "ERROR", "SUMMARY_MISSING_SOURCE", f"{sid} derives from missing state item {dep_id}")
                tainted_summaries.setdefault(sid, []).append(f"missing {dep_id}")
                continue
            registry, item = record
            if not is_active(registry, item):
                add(
                    findings,
                    "WARN",
                    "SUMMARY_STALE_SOURCE",
                    f"{sid} derives from inactive {registry[:-1] if registry.endswith('s') else registry} {dep_id} (status={item.get('status')})",
                )
                tainted_summaries.setdefault(sid, []).append(f"stale {dep_id}")

    # Propagate taint across summary -> summary derivation chains.
    changed = True
    while changed:
        changed = False
        for sid, summary in summaries.items():
            deps = summary.get("derived_from", []) or []
            inherited = [str(dep) for dep in deps if str(dep) in tainted_summaries]
            if inherited and sid not in tainted_summaries:
                tainted_summaries[sid] = [f"tainted summary {x}" for x in inherited]
                changed = True

    # Validate context entries.
    entries = manifest.get("context_entries", [])
    if not isinstance(entries, list):
        add(findings, "ERROR", "MANIFEST_STRUCTURE", "context_entries must be an array")
        return findings

    seen_entry_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            add(findings, "ERROR", "MANIFEST_STRUCTURE", "context_entries contains a non-object")
            continue
        eid = str(entry.get("id", ""))
        if not eid:
            add(findings, "ERROR", "CONTEXT_ENTRY_NO_ID", "A context entry is missing id")
        elif eid in seen_entry_ids:
            add(findings, "ERROR", "CONTEXT_ENTRY_DUPLICATE_ID", f"Duplicate context entry id {eid}")
        else:
            seen_entry_ids.add(eid)

        kind = entry.get("kind")
        if kind == "state":
            source_id = str(entry.get("source_id", ""))
            record = index.get(source_id)
            if record is None:
                add(findings, "ERROR", "CONTEXT_MISSING_SOURCE", f"{eid or '<entry>'} references missing state item {source_id!r}")
                continue
            registry, item = record
            declared_registry = entry.get("registry")
            if declared_registry and declared_registry != registry:
                add(
                    findings,
                    "ERROR",
                    "CONTEXT_REGISTRY_MISMATCH",
                    f"{eid} says {source_id} belongs to {declared_registry}, but current state places it in {registry}",
                )

            expected_authority = effective_authority(registry, item)
            expected_trust = effective_trust(item)
            expected_plane = "control" if registry == "instructions" else "data"
            if entry.get("authority") and entry.get("authority") != expected_authority:
                add(findings, "ERROR", "CONTEXT_AUTHORITY_MISMATCH", f"{eid} authority for {source_id} is {entry.get('authority')!r}, expected {expected_authority!r}")
            if entry.get("trust_level") and entry.get("trust_level") != expected_trust:
                add(findings, "ERROR", "CONTEXT_TRUST_MISMATCH", f"{eid} trust_level for {source_id} is {entry.get('trust_level')!r}, expected {expected_trust!r}")
            if entry.get("plane") and entry.get("plane") != expected_plane:
                add(findings, "ERROR", "CONTEXT_PLANE_MISMATCH", f"{eid} places {source_id} in {entry.get('plane')!r}, expected {expected_plane!r}")
            if registry == "instructions":
                if expected_authority != "control":
                    add(findings, "ERROR", "INSTRUCTION_NOT_CONTROL", f"{eid} includes instruction {source_id} without control authority")
                if expected_trust not in ("trusted", "reviewed"):
                    add(findings, "ERROR", "UNTRUSTED_CONTROL", f"{eid} includes instruction {source_id} with trust_level={expected_trust!r}")
            elif expected_authority == "control":
                add(findings, "ERROR", "DATA_AUTHORITY_ESCALATION", f"{eid} includes non-instruction {source_id} claiming control authority")

            if not is_active(registry, item):
                severity = "ERROR" if registry == "instructions" else "WARN"
                add(
                    findings,
                    severity,
                    "STALE_CONTEXT_ITEM",
                    f"{eid} includes inactive {source_id} from {registry} (status={item.get('status')})",
                )
                if registry == "instructions":
                    successor = active_instruction_successor(item, instructions)
                    if successor:
                        add(
                            findings,
                            "ERROR",
                            "SHADOWED_INSTRUCTION",
                            f"{eid} includes stale instruction {source_id}; active instruction {successor} has the same key/scope identity",
                        )
            snapshot_hash = entry.get("snapshot_hash")
            if not snapshot_hash:
                add(findings, "WARN", "CONTEXT_NO_SNAPSHOT_HASH", f"{eid} has no snapshot_hash")
            elif snapshot_hash != digest(item):
                add(
                    findings,
                    "ERROR",
                    "CONTEXT_SNAPSHOT_MISMATCH",
                    f"{eid} snapshot of {source_id} no longer matches the current state item",
                )

        elif kind == "summary":
            source_id = str(entry.get("source_id", ""))
            summary = summaries.get(source_id)
            if summary is None:
                add(findings, "ERROR", "CONTEXT_MISSING_SUMMARY", f"{eid} references missing summary {source_id!r}")
                continue
            expected = digest({
                "text": summary.get("text", ""),
                "derived_from": summary.get("derived_from", []),
            })
            snapshot_hash = entry.get("snapshot_hash")
            if snapshot_hash and snapshot_hash != expected:
                add(findings, "ERROR", "SUMMARY_SNAPSHOT_MISMATCH", f"{eid} snapshot of summary {source_id} no longer matches")
            if source_id in tainted_summaries:
                reasons = "; ".join(tainted_summaries[source_id])
                add(findings, "ERROR", "TAINTED_CONTEXT", f"{eid} includes tainted summary {source_id}: {reasons}")

        elif kind == "unmanaged":
            label = entry.get("label") or eid or "<entry>"
            add(
                findings,
                "WARN",
                "UNMANAGED_CONTEXT",
                f"{label} is declared as unmanaged context; its lifecycle and provenance cannot be verified",
            )
        else:
            add(findings, "ERROR", "UNKNOWN_CONTEXT_KIND", f"{eid or '<entry>'} has unsupported kind {kind!r}")

    # Emit one aggregate finding per tainted summary even if it is not currently included.
    for sid, reasons in sorted(tainted_summaries.items()):
        add(findings, "WARN", "TAINTED_SUMMARY", f"{sid} is tainted: {'; '.join(reasons)}")

    findings.sort(key=lambda x: (-SEVERITY_ORDER.get(x.severity, 0), x.code, x.message))
    return findings


def explain_manifest(state: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    index = state_index(state)
    summaries = summary_index(manifest)
    findings = lint_manifest(state, manifest)
    nodes: list[dict[str, Any]] = []

    for entry in manifest.get("context_entries", []) or []:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        source_id = str(entry.get("source_id", ""))
        row: dict[str, Any] = {
            "context_entry": entry.get("id"),
            "kind": kind,
            "source_id": source_id or None,
            "included_via": entry.get("included_via"),
        }
        if kind == "state" and source_id in index:
            registry, item = index[source_id]
            row.update({
                "registry": registry,
                "status": item.get("status"),
                "authority": effective_authority(registry, item),
                "trust_level": effective_trust(item),
                "origin_kind": origin_kind(item),
                "plane": "control" if registry == "instructions" else "data",
                "statement": item.get("statement") or item.get("instruction") or item.get("decision"),
            })
        elif kind == "summary" and source_id in summaries:
            summary = summaries[source_id]
            row.update({
                "derived_from": summary.get("derived_from", []),
                "text": summary.get("text", ""),
            })
        elif kind == "unmanaged":
            row.update({"label": entry.get("label"), "reason": entry.get("reason")})
        nodes.append(row)

    return {
        "project": state.get("project", {}).get("name"),
        "manifest_created_at": manifest.get("created_at"),
        "declared_influences": nodes,
        "finding_counts": {
            "ERROR": sum(1 for x in findings if x.severity == "ERROR"),
            "WARN": sum(1 for x in findings if x.severity == "WARN"),
            "INFO": sum(1 for x in findings if x.severity == "INFO"),
        },
        "findings": [x.__dict__ for x in findings],
        "visibility_limit": "Only declared context is traceable. Opaque host/system prompts are not introspected.",
    }


def render_findings(findings: list[Finding]) -> str:
    if not findings:
        return "Context Trace: clean\n"
    lines = [f"Context Trace: {len(findings)} finding(s)"]
    for finding in findings:
        lines.append(f"[{finding.severity}] {finding.code}: {finding.message}")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trace context provenance and detect stale/contaminated declared context")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="Build a context manifest from governed state")
    p_build.add_argument("state", type=Path)
    p_build.add_argument("--ids", nargs="*", default=[], help="State IDs materially included; omit to include all active state")
    p_build.add_argument("--output", "-o", type=Path)
    p_build.add_argument("--at", dest="created_at")

    p_lint = sub.add_parser("lint", help="Lint a context manifest against current governed state")
    p_lint.add_argument("state", type=Path)
    p_lint.add_argument("manifest", type=Path)
    p_lint.add_argument("--json", action="store_true")
    p_lint.add_argument("--strict", action="store_true", help="Exit non-zero on warnings as well as errors")

    p_explain = sub.add_parser("explain", help="Explain declared influences and contamination findings")
    p_explain.add_argument("state", type=Path)
    p_explain.add_argument("manifest", type=Path)
    p_explain.add_argument("--json", action="store_true")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "build":
            state = load_json(args.state)
            require_version(state, label="state")
            manifest = build_manifest(state, args.ids, created_at=args.created_at)
            dump_json(manifest, args.output)
            return 0

        state = load_json(args.state)
        manifest = load_json(args.manifest)
        require_version(state, label="state")
        require_version(manifest, label="context manifest")

        if args.command == "lint":
            findings = lint_manifest(state, manifest)
            if args.json:
                sys.stdout.write(json.dumps([x.__dict__ for x in findings], indent=2, ensure_ascii=False) + "\n")
            else:
                sys.stdout.write(render_findings(findings))
            has_error = any(x.severity == "ERROR" for x in findings)
            has_warn = any(x.severity == "WARN" for x in findings)
            return 1 if has_error or (args.strict and has_warn) else 0

        if args.command == "explain":
            report = explain_manifest(state, manifest)
            if args.json:
                sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
            else:
                sys.stdout.write(f"Context provenance for {report.get('project') or '<project>'}\n")
                for node in report["declared_influences"]:
                    source = node.get("source_id") or node.get("label") or "<unmanaged>"
                    sys.stdout.write(f"- {node.get('context_entry')}: {node.get('kind')} -> {source}\n")
                counts = report["finding_counts"]
                sys.stdout.write(f"Findings: {counts['ERROR']} error(s), {counts['WARN']} warning(s), {counts['INFO']} info\n")
                if report["findings"]:
                    for finding in report["findings"]:
                        sys.stdout.write(f"[{finding['severity']}] {finding['code']}: {finding['message']}\n")
                sys.stdout.write("Visibility: declared context only; opaque host/system prompts are not introspected.\n")
            return 0

        raise AssertionError("unreachable")
    except (OSError, SafeIOError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
