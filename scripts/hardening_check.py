#!/usr/bin/env python3
"""Pre-release hardening checks for governed state and declared context.

This is not a vulnerability scanner for the host platform. It checks the attack
surface this project can actually observe: strict JSON parsing, governed-state
invariants, trust-boundary metadata, suspicious control-like text in data, and
(optional) declared-context provenance.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import context_lint
import context_trace
from safe_io import SafeIOError, atomic_write_json, read_json, require_version


@dataclass(frozen=True)
class SecurityFinding:
    severity: str
    code: str
    message: str


REGISTRIES = {
    "facts": "F-",
    "assumptions": "A-",
    "instructions": "I-",
    "decisions": "D-",
    "open_items": "O-",
}
CONTROL_LIKE_PATTERNS = [
    re.compile(r"\bignore\s+(all\s+)?(previous|prior)\b", re.I),
    re.compile(r"\bsystem\s+prompt\b", re.I),
    re.compile(r"\bdeveloper\s+message\b", re.I),
    re.compile(r"\bact\s+as\b", re.I),
    re.compile(r"忽略.{0,12}(之前|以上|先前).{0,12}(指令|提示)", re.I),
    re.compile(r"系统提示词|开发者消息|按照以下指令", re.I),
]
EXTERNAL_ORIGINS = {"web", "file", "tool", "import", "retrieval"}


def _add(out: list[SecurityFinding], severity: str, code: str, message: str) -> None:
    out.append(SecurityFinding(severity, code, message))


def _iter_strings(value: Any, path: str = ""):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _iter_strings(v, f"{path}/{k}" if path else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _iter_strings(v, f"{path}/{i}" if path else str(i))


def audit_state(state: dict[str, Any]) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []

    # Reuse semantic invariant checks as part of the security boundary.
    for finding in context_lint.lint(state):
        if finding.severity in {"ERROR", "WARN"}:
            _add(findings, finding.severity, f"LINT_{finding.code}", finding.message)

    seen_ids: set[str] = set()
    for registry, prefix in REGISTRIES.items():
        items = state.get(registry, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id", ""))
            if item_id:
                if not item_id.startswith(prefix):
                    _add(findings, "ERROR", "ID_NAMESPACE", f"{item_id} is stored in {registry} but does not use prefix {prefix}")
                if item_id in seen_ids:
                    _add(findings, "ERROR", "DUPLICATE_ID", f"duplicate governed id {item_id}")
                seen_ids.add(item_id)

            authority = item.get("authority")
            origin = item.get("origin") if isinstance(item.get("origin"), dict) else {}
            origin_kind = str(origin.get("kind", ""))
            trust = str(item.get("trust_level", ""))

            if registry == "instructions" and item.get("status") == "active":
                if origin_kind in EXTERNAL_ORIGINS and trust == "trusted":
                    _add(
                        findings,
                        "WARN",
                        "EXTERNAL_CONTROL_TRUST",
                        f"{item_id or '<instruction>'} is active control from external origin={origin_kind!r} marked trusted without an explicit review boundary",
                    )
            elif authority != "control":
                # Control-like text is allowed in data, but surface it so tests can
                # verify that it remains on the data plane.
                for text_path, text in _iter_strings(item):
                    if text_path.endswith("/origin/ref"):
                        continue
                    if any(pattern.search(text) for pattern in CONTROL_LIKE_PATTERNS):
                        _add(
                            findings,
                            "INFO",
                            "CONTROL_LIKE_DATA",
                            f"{item_id or registry} contains control-like text at {text_path}; it must remain data-plane content",
                        )
                        break

    return findings


def build_report(state: dict[str, Any], manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    findings = audit_state(state)
    if manifest is not None:
        for finding in context_trace.lint_manifest(state, manifest):
            if finding.severity in {"ERROR", "WARN"}:
                findings.append(SecurityFinding(finding.severity, f"TRACE_{finding.code}", finding.message))
    counts = {severity: sum(1 for f in findings if f.severity == severity) for severity in ("ERROR", "WARN", "INFO")}
    return {
        "status": "fail" if counts["ERROR"] else ("review" if counts["WARN"] else "pass"),
        "counts": counts,
        "findings": [asdict(f) for f in findings],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run hardening checks over governed state and optional context manifest")
    parser.add_argument("state", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", "-o", type=Path)
    parser.add_argument("--strict", action="store_true", help="Treat warnings as a non-zero result")
    args = parser.parse_args(argv)
    try:
        state = read_json(args.state)
        require_version(state, label="state")
        manifest = read_json(args.manifest) if args.manifest else None
        if manifest is not None:
            require_version(manifest, label="context manifest")
        report = build_report(state, manifest)
        if args.output:
            atomic_write_json(args.output, report)
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["counts"]["ERROR"]:
            return 1
        if args.strict and report["counts"]["WARN"]:
            return 1
        return 0
    except (OSError, SafeIOError, ValueError) as exc:
        print(f"hardening-check: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
