#!/usr/bin/env python3
"""Pre-release audit for Agent State Governance.

Standard-library at runtime; if ``jsonschema`` is installed (development only),
validate published schemas and representative instances as well.
"""
from __future__ import annotations

import argparse
import json
import os
import py_compile
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

# The release audit must be observational: importing project modules must not
# create bytecode artifacts in the tree it is auditing.
sys.dont_write_bytecode = True

from safe_io import PROTOCOL_VERSION, SafeIOError, loads_json_strict


@dataclass
class Finding:
    severity: str
    code: str
    message: str


NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def add(findings: list[Finding], severity: str, code: str, message: str) -> None:
    findings.append(Finding(severity, code, message))


def parse_skill_frontmatter(path: Path) -> tuple[dict[str, str], int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md must start with YAML frontmatter")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration as exc:
        raise ValueError("SKILL.md frontmatter is not closed") from exc
    meta: dict[str, str] = {}
    for raw in lines[1:end]:
        if not raw.strip():
            continue
        if ":" not in raw:
            raise ValueError(f"unsupported frontmatter line: {raw!r}")
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith(('"', "'")) and value.endswith(value[0]) and len(value) >= 2:
            value = value[1:-1]
        if key in meta:
            raise ValueError(f"duplicate frontmatter key: {key}")
        meta[key] = value
    return meta, len(lines)


def audit_skill(findings: list[Finding]) -> None:
    path = ROOT / "SKILL.md"
    if not path.exists():
        add(findings, "ERROR", "SKILL_MISSING", "SKILL.md is required")
        return
    try:
        meta, line_count = parse_skill_frontmatter(path)
    except (OSError, ValueError) as exc:
        add(findings, "ERROR", "SKILL_FRONTMATTER", str(exc))
        return
    keys = set(meta)
    if keys != {"name", "description"}:
        add(findings, "ERROR", "SKILL_FRONTMATTER_KEYS", f"frontmatter keys must be only name and description; got {sorted(keys)}")
    name = meta.get("name", "")
    desc = meta.get("description", "")
    if not NAME_RE.fullmatch(name) or len(name) > 64:
        add(findings, "ERROR", "SKILL_NAME", f"invalid skill name: {name!r}")
    if name and name != ROOT.name:
        add(findings, "ERROR", "SKILL_DIR_NAME", f"skill name {name!r} must match directory {ROOT.name!r}")
    if not desc or len(desc) > 1024:
        add(findings, "ERROR", "SKILL_DESCRIPTION", f"description length must be 1..1024; got {len(desc)}")
    if line_count > 500:
        add(findings, "WARN", "SKILL_SIZE", f"SKILL.md has {line_count} lines; progressive disclosure guidance recommends keeping it below ~500")


def audit_openai_metadata(findings: list[Finding]) -> None:
    path = ROOT / "agents" / "openai.yaml"
    if not path.exists():
        add(findings, "WARN", "OPENAI_METADATA_MISSING", "agents/openai.yaml is recommended for OpenAI skill UI metadata")
        return
    text = path.read_text(encoding="utf-8")
    if not re.search(r"(?m)^interface:\s*$", text):
        add(findings, "ERROR", "OPENAI_METADATA_INTERFACE", "agents/openai.yaml must contain interface:")
    for key in ("display_name", "short_description", "default_prompt"):
        m = re.search(rf'(?m)^\s{{2}}{re.escape(key)}:\s*["\'](.+?)["\']\s*$', text)
        if not m or not m.group(1).strip():
            add(findings, "ERROR", "OPENAI_METADATA_FIELD", f"agents/openai.yaml missing non-empty {key}")


def iter_json_files() -> Iterable[Path]:
    for folder in ("schemas", "examples", "templates", "security"):
        base = ROOT / folder
        if base.exists():
            yield from sorted(base.rglob("*.json"))


def audit_json(findings: list[Finding]) -> dict[Path, object]:
    parsed: dict[Path, object] = {}
    for path in iter_json_files():
        try:
            parsed[path] = loads_json_strict(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SafeIOError) as exc:
            add(findings, "ERROR", "JSON_INVALID", f"{path.relative_to(ROOT)}: {exc}")
    for path in (ROOT / "examples").glob("*.json"):
        obj = parsed.get(path)
        if isinstance(obj, dict) and {"project", "facts", "assumptions", "instructions", "decisions", "open_items"} <= set(obj):
            if obj.get("version") != PROTOCOL_VERSION:
                add(findings, "ERROR", "STATE_VERSION", f"{path.relative_to(ROOT)} uses {obj.get('version')!r}; expected {PROTOCOL_VERSION!r}")
    template = ROOT / "templates" / "state.json"
    obj = parsed.get(template)
    if isinstance(obj, dict):
        if obj.get("version") != PROTOCOL_VERSION:
            add(findings, "ERROR", "TEMPLATE_VERSION", "templates/state.json protocol version is stale")
        name = obj.get("project", {}).get("name") if isinstance(obj.get("project"), dict) else None
        if not isinstance(name, str) or not name.strip():
            add(findings, "ERROR", "TEMPLATE_PROJECT_NAME", "templates/state.json must validate without requiring an immediate edit")
    return parsed


def audit_json_schemas(findings: list[Finding], parsed: dict[Path, object], generated: dict[str, Path] | None = None) -> None:
    try:
        from jsonschema import Draft202012Validator, FormatChecker  # type: ignore
    except ImportError:
        add(findings, "WARN", "JSONSCHEMA_UNAVAILABLE", "jsonschema is not installed; schema meta-validation and instance validation were skipped")
        return
    schemas: dict[str, dict] = {}
    for path in sorted((ROOT / "schemas").glob("*.json")):
        obj = parsed.get(path)
        if not isinstance(obj, dict):
            continue
        try:
            Draft202012Validator.check_schema(obj)
        except Exception as exc:  # jsonschema exposes several validation exceptions
            add(findings, "ERROR", "SCHEMA_INVALID", f"{path.relative_to(ROOT)}: {exc}")
            continue
        schemas[path.name] = obj

    static_map = {
        "state.schema.json": [
            "examples/sample-state.json", "examples/broken-state.json", "examples/diff-before.json",
            "examples/diff-after.json", "examples/review-state.json", "examples/revalidated-state.json",
            "templates/state.json",
        ],
        "semantic-candidates.schema.json": ["examples/semantic-candidates.json"],
        "context-manifest.schema.json": ["examples/context-manifest-clean.json", "examples/context-manifest-contaminated.json"],
        "revalidation-plan.schema.json": ["examples/revalidation-plan.json"],
        "revalidation-resolution.schema.json": ["examples/revalidation-resolution.json"],
        "handoff.schema.json": ["examples/handoff-board.json", "templates/handoff.json"],
    }
    for schema_name, rels in static_map.items():
        schema = schemas.get(schema_name)
        if schema is None:
            continue
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        for rel in rels:
            path = ROOT / rel
            obj = parsed.get(path)
            if obj is None:
                continue
            errors = sorted(validator.iter_errors(obj), key=lambda e: list(e.path))
            for err in errors:
                add(findings, "ERROR", "SCHEMA_INSTANCE", f"{rel} vs {schema_name} at {list(err.path)}: {err.message}")

    if generated:
        gen_map = {
            "retrieval": "retrieval-gate-report.schema.json",
            "compiled": "compiled-context.schema.json",
            "manifest": "context-manifest.schema.json",
            "plan": "revalidation-plan.schema.json",
        }
        for key, schema_name in gen_map.items():
            path = generated.get(key)
            schema = schemas.get(schema_name)
            if path is None or schema is None or not path.exists():
                continue
            obj = json.loads(path.read_text(encoding="utf-8"))
            for err in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(obj):
                add(findings, "ERROR", "GENERATED_SCHEMA_INSTANCE", f"generated {key} vs {schema_name} at {list(err.path)}: {err.message}")


def audit_python(findings: list[Finding]) -> None:
    # Compile into a temporary directory so the audit never pollutes the
    # worktree with __pycache__ / .pyc files that it later flags as junk.
    with tempfile.TemporaryDirectory(prefix="asg-pycompile-") as tmp:
        tmp_root = Path(tmp)
        for index, path in enumerate(sorted((ROOT / "scripts").glob("*.py")) + sorted((ROOT / "tests").glob("*.py"))):
            cfile = tmp_root / f"{index:04d}-{path.stem}.pyc"
            try:
                py_compile.compile(str(path), cfile=str(cfile), doraise=True)
            except py_compile.PyCompileError as exc:
                add(findings, "ERROR", "PY_COMPILE", f"{path.relative_to(ROOT)}: {exc.msg}")


def run_cmd(findings: list[Finding], code: str, argv: list[str], *, cwd: Path = ROOT, quiet: bool = True) -> subprocess.CompletedProcess[str] | None:
    try:
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUTF8"] = "1"
        cp = subprocess.run(argv, cwd=cwd, capture_output=quiet, text=True, encoding="utf-8", timeout=60, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        add(findings, "ERROR", code, f"command failed to start: {argv!r}: {exc}")
        return None
    if cp.returncode != 0:
        detail = ((cp.stderr or cp.stdout) if quiet else "").strip()
        add(findings, "ERROR", code, f"exit {cp.returncode}: {' '.join(argv)}" + (f" :: {detail[:800]}" if detail else ""))
    return cp


def audit_cli_help(findings: list[Finding]) -> None:
    cli_scripts = [
        "context_lint.py", "state_diff.py", "revalidate.py", "state_vcs.py", "context_trace.py",
        "context_compile.py", "retrieval_gate.py", "hardening_check.py", "release_audit.py", "build_release.py",
        "handoff.py",
    ]
    for script in cli_scripts:
        path = ROOT / "scripts" / script
        if not path.exists():
            add(findings, "ERROR", "CLI_MISSING", f"missing scripts/{script}")
            continue
        run_cmd(findings, "CLI_HELP", [sys.executable, str(path), "--help"])


def audit_smoke(findings: list[Finding]) -> dict[str, Path]:
    generated: dict[str, Path] = {}
    with tempfile.TemporaryDirectory(prefix="asg-release-audit-") as td:
        tmp = Path(td)
        commands: list[tuple[str, list[str]]] = [
            ("SMOKE_LINT", [sys.executable, "scripts/context_lint.py", "examples/sample-state.json", "--strict"]),
            ("SMOKE_HARDEN", [sys.executable, "scripts/hardening_check.py", "examples/sample-state.json", "--strict"]),
            ("SMOKE_DIFF", [sys.executable, "scripts/state_diff.py", "examples/diff-before.json", "examples/diff-after.json", "--json"]),
        ]
        for code, argv in commands:
            run_cmd(findings, code, argv)

        plan = tmp / "plan.json"
        run_cmd(findings, "SMOKE_REVALIDATION_PLAN", [sys.executable, "scripts/revalidate.py", "plan", "examples/review-state.json", "--output", str(plan)])
        resolved = tmp / "resolved.json"
        run_cmd(findings, "SMOKE_REVALIDATION_APPLY", [sys.executable, "scripts/revalidate.py", "apply", "examples/review-state.json", "examples/revalidation-resolution.json", "--output", str(resolved)])
        run_cmd(findings, "SMOKE_REVALIDATION_LINT", [sys.executable, "scripts/context_lint.py", str(resolved), "--strict"])
        generated["plan"] = ROOT / ".__audit_plan_placeholder__"  # overwritten below after copy

        retrieval = tmp / "retrieval.json"
        run_cmd(findings, "SMOKE_RETRIEVAL", [sys.executable, "scripts/retrieval_gate.py", "examples/sample-state.json", "examples/compiler-task.json", "examples/semantic-candidates.json", "--output", str(retrieval), "--strict"])

        compiled = tmp / "compiled.json"
        context = tmp / "context.txt"
        manifest = tmp / "manifest.json"
        run_cmd(findings, "SMOKE_COMPILE", [
            sys.executable, "scripts/context_compile.py", "examples/sample-state.json",
            "--task-file", "examples/compiler-task.json", "--semantic-candidates", "examples/semantic-candidates.json",
            "--output", str(compiled), "--context-output", str(context), "--manifest-output", str(manifest),
            "--at", "2026-09-17T00:00:00Z",
        ])
        run_cmd(findings, "SMOKE_TRACE", [sys.executable, "scripts/context_trace.py", "lint", "examples/sample-state.json", str(manifest), "--strict"])

        vcs = tmp / "vcs"
        run_cmd(findings, "SMOKE_VCS_INIT", [sys.executable, "scripts/state_vcs.py", "--repo", str(vcs), "init", "examples/sample-state.json", "--at", "2026-09-17T00:00:00Z"])
        run_cmd(findings, "SMOKE_VCS_BRANCH", [sys.executable, "scripts/state_vcs.py", "--repo", str(vcs), "branch", "scenario-b"])
        run_cmd(findings, "SMOKE_VCS_DIFF", [sys.executable, "scripts/state_vcs.py", "--repo", str(vcs), "diff", "main", "scenario-b", "--json"])
        run_cmd(findings, "SMOKE_VCS_MERGE", [sys.executable, "scripts/state_vcs.py", "--repo", str(vcs), "merge", "scenario-b", "--json"])

        handoff = tmp / "handoff.json"
        run_cmd(findings, "SMOKE_HANDOFF_INIT", [
            sys.executable, "scripts/handoff.py", "--board", str(handoff), "init",
            "--project-name", "audit", "--objective", "Parallel audit work",
            "--state", "examples/sample-state.json", "--at", "2026-09-17T00:00:00Z",
        ])
        run_cmd(findings, "SMOKE_HANDOFF_ADD", [
            sys.executable, "scripts/handoff.py", "--board", str(handoff), "add", "W-audit",
            "--title", "Audit", "--objective", "Run checks", "--accept", "Checks pass",
            "--scope", "release-audit",
            "--expected-revision", "0", "--at", "2026-09-17T00:01:00Z",
        ])
        run_cmd(findings, "SMOKE_HANDOFF_REGISTER", [
            sys.executable, "scripts/handoff.py", "--board", str(handoff), "register", "audit-agent",
            "--thread-ref", "release-audit", "--expected-revision", "1", "--at", "2026-09-17T00:02:00Z",
        ])
        run_cmd(findings, "SMOKE_HANDOFF_CLAIM", [
            sys.executable, "scripts/handoff.py", "--board", str(handoff), "claim", "W-audit",
            "--agent", "audit-agent", "--expected-revision", "2", "--at", "2026-09-17T00:03:00Z",
        ])
        run_cmd(findings, "SMOKE_HANDOFF_COMPLETE", [
            sys.executable, "scripts/handoff.py", "--board", str(handoff), "complete", "W-audit",
            "--agent", "audit-agent", "--summary", "Checks passed", "--output", "audit.txt",
            "--expected-revision", "3", "--at", "2026-09-17T00:04:00Z",
        ])
        run_cmd(findings, "SMOKE_HANDOFF_LINT", [
            sys.executable, "scripts/handoff.py", "--board", str(handoff), "lint",
            "--state", "examples/sample-state.json", "--strict",
        ])

        # Keep generated documents alive for schema checks after the temp dir closes.
        cache = Path(tempfile.mkdtemp(prefix="asg-schema-audit-"))
        mapping = {"plan": plan, "retrieval": retrieval, "compiled": compiled, "manifest": manifest}
        generated = {}
        for key, src in mapping.items():
            dst = cache / f"{key}.json"
            if src.exists():
                dst.write_bytes(src.read_bytes())
                generated[key] = dst
        return generated


def cleanup_generated(generated: dict[str, Path]) -> None:
    caches = {path.parent for path in generated.values()}
    for path in generated.values():
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    for cache in caches:
        try:
            cache.rmdir()
        except OSError:
            pass


def audit_markdown_links(findings: list[Finding]) -> None:
    for path in [ROOT / "README.md", ROOT / "README.zh-CN.md", ROOT / "SKILL.md", ROOT / "SECURITY.md", ROOT / "CONTRIBUTING.md", *sorted((ROOT / "references").glob("*.md"))]:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for target in MD_LINK_RE.findall(text):
            target = target.strip().split("#", 1)[0]
            if not target or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", target) or target.startswith("mailto:"):
                continue
            resolved = (path.parent / target).resolve()
            try:
                resolved.relative_to(ROOT.resolve())
            except ValueError:
                add(findings, "WARN", "LINK_OUTSIDE_REPO", f"{path.relative_to(ROOT)} -> {target}")
                continue
            if not resolved.exists():
                add(findings, "ERROR", "BROKEN_LOCAL_LINK", f"{path.relative_to(ROOT)} -> {target}")


def audit_repo_metadata(findings: list[Finding]) -> None:
    required = ["README.md", "README.zh-CN.md", "LICENSE", "CHANGELOG.md", "SECURITY.md", "CONTRIBUTING.md", "VERSION"]
    for rel in required:
        if not (ROOT / rel).exists():
            add(findings, "ERROR", "REPO_FILE_MISSING", rel)
    try:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return
    if not SEMVER_RE.fullmatch(version):
        add(findings, "ERROR", "VERSION_FORMAT", f"invalid VERSION: {version!r}")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8") if (ROOT / "CHANGELOG.md").exists() else ""
    if version and f"v{version}" not in changelog:
        add(findings, "ERROR", "CHANGELOG_VERSION", f"CHANGELOG.md has no v{version} section")


def audit_hygiene(findings: list[Finding]) -> None:
    junk = []
    for path in ROOT.rglob("*"):
        if ".git" in path.parts:
            continue
        if path.name == ".DS_Store" or path.suffix in {".pyc", ".pyo"} or "__pycache__" in path.parts or ".agent-state" in path.parts:
            junk.append(path)
    if junk:
        add(findings, "WARN", "WORKTREE_JUNK", f"{len(junk)} cache/local-state path(s) exist; build_release.py excludes them")


def run_full_tests(findings: list[Finding]) -> None:
    run_cmd(findings, "UNIT_TESTS", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"])


def print_findings(findings: list[Finding]) -> None:
    for f in findings:
        print(f"[{f.severity}] {f.code}: {f.message}")
    counts = {s: sum(1 for f in findings if f.severity == s) for s in ("ERROR", "WARN")}
    print(f"Release audit: {counts['ERROR']} error(s), {counts['WARN']} warning(s)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Agent State Governance before a release")
    parser.add_argument("--full", action="store_true", help="also run the complete unit test suite")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failure")
    args = parser.parse_args(argv)

    findings: list[Finding] = []
    generated: dict[str, Path] = {}
    try:
        audit_repo_metadata(findings)
        audit_skill(findings)
        audit_openai_metadata(findings)
        parsed = audit_json(findings)
        audit_python(findings)
        audit_cli_help(findings)
        audit_markdown_links(findings)
        audit_hygiene(findings)
        generated = audit_smoke(findings)
        audit_json_schemas(findings, parsed, generated)
        if args.full:
            run_full_tests(findings)
    finally:
        cleanup_generated(generated)

    print_findings(findings)
    has_error = any(f.severity == "ERROR" for f in findings)
    has_warn = any(f.severity == "WARN" for f in findings)
    return 1 if has_error or (args.strict and has_warn) else 0


if __name__ == "__main__":
    raise SystemExit(main())
