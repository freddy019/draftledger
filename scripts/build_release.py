#!/usr/bin/env python3
"""Build a deterministic release ZIP after running the full release audit."""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_PARTS = {".git", "__pycache__", ".agent-state", ".release-audit-cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
RELEASE_DIRS = {".github", "agents", "examples", "references", "schemas", "scripts", "security", "templates", "tests"}
RELEASE_FILES = {".gitignore", ".gitattributes", "CHANGELOG.md", "CONTRIBUTING.md", "LICENSE", "README.md", "README.zh-CN.md", "SECURITY.md", "SKILL.md", "VERSION", "requirements-dev.txt", "RELEASE_NOTES.md", "FINAL_AUDIT.md", "PUBLISHING.md"}


def include(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if rel.parts[0] not in RELEASE_DIRS and rel.as_posix() not in RELEASE_FILES:
        return False
    if path.is_symlink() or any((ROOT / parent).is_symlink() for parent in rel.parents):
        raise ValueError(f"release inputs must not be symlinks: {path}")
    if any(part in EXCLUDED_PARTS for part in rel.parts):
        return False
    if path.name == ".DS_Store" or path.suffix in EXCLUDED_SUFFIXES:
        return False
    return path.is_file()


def deterministic_zip(output: Path) -> str:
    if output.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError("release output must be outside the source repository")
    files = sorted((p for p in ROOT.rglob("*") if include(p)), key=lambda p: p.as_posix())
    root_name = ROOT.name
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(suffix=".zip", dir=output.parent)
    os.close(fd)
    try:
        _write_zip(Path(temporary), files, root_name)
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    sidecar = output.with_suffix(output.suffix + ".sha256")
    sidecar.write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    return digest


def _write_zip(output: Path, files: list[Path], root_name: str) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(f"{root_name}/{rel}", date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            mode = 0o755 if path.parent.name == "scripts" and path.suffix == ".py" else 0o644
            info.external_attr = (mode & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit and build DraftLedger release archive")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-audit", action="store_true")
    args = parser.parse_args(argv)

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    output = args.output or ROOT.parent / f"{ROOT.name}-v{version}.zip"
    if not args.skip_audit:
        cp = subprocess.run([sys.executable, str(ROOT / "scripts" / "release_audit.py"), "--full", "--strict"], cwd=ROOT)
        if cp.returncode:
            return cp.returncode
    digest = deterministic_zip(output)
    print(f"Built {output}")
    print(f"SHA256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
