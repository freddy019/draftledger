#!/usr/bin/env python3
"""Hardened JSON I/O primitives for Agent State Governance.

Standard-library only. Rejects duplicate JSON keys and non-finite numbers,
applies conservative resource limits, and writes files atomically.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DEFAULT_MAX_JSON_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_NODES = 100_000
DEFAULT_MAX_DEPTH = 64
DEFAULT_MAX_STRING_BYTES = 1 * 1024 * 1024
PROTOCOL_VERSION = "1.0"


class SafeIOError(ValueError):
    pass


def _reject_constant(value: str) -> None:
    raise SafeIOError(f"non-finite JSON number is not allowed: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise SafeIOError(f"duplicate JSON key: {key!r}")
        out[key] = value
    return out


def validate_complexity(
    value: Any,
    *,
    max_nodes: int = DEFAULT_MAX_NODES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_string_bytes: int = DEFAULT_MAX_STRING_BYTES,
) -> None:
    stack: list[tuple[Any, int]] = [(value, 0)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > max_nodes:
            raise SafeIOError(f"JSON exceeds node limit ({max_nodes})")
        if depth > max_depth:
            raise SafeIOError(f"JSON exceeds nesting depth limit ({max_depth})")
        if isinstance(current, str):
            if len(current.encode("utf-8")) > max_string_bytes:
                raise SafeIOError(f"JSON string exceeds byte limit ({max_string_bytes})")
        elif isinstance(current, float) and not math.isfinite(current):
            raise SafeIOError("non-finite JSON number is not allowed")
        elif isinstance(current, dict):
            for key, child in current.items():
                if len(str(key).encode("utf-8")) > max_string_bytes:
                    raise SafeIOError(f"JSON object key exceeds byte limit ({max_string_bytes})")
                stack.append((child, depth + 1))
        elif isinstance(current, list):
            for child in current:
                stack.append((child, depth + 1))



def require_version(value: Any, *, expected: str = PROTOCOL_VERSION, label: str = "document") -> None:
    """Reject unsupported machine-readable protocol versions.

    Version checks are explicit so newer/older formats do not silently pass through
    tools that may interpret lifecycle fields differently.
    """
    if not isinstance(value, dict):
        raise SafeIOError(f"{label} must be a JSON object")
    actual = value.get("version")
    if actual != expected:
        raise SafeIOError(f"unsupported {label} version {actual!r}; expected {expected!r}")

def loads_json_strict(
    text: str,
    *,
    max_nodes: int = DEFAULT_MAX_NODES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_string_bytes: int = DEFAULT_MAX_STRING_BYTES,
) -> Any:
    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except RecursionError as exc:
        raise SafeIOError("JSON nesting is too deep to parse safely") from exc
    except json.JSONDecodeError as exc:
        raise SafeIOError(str(exc)) from exc
    validate_complexity(
        value,
        max_nodes=max_nodes,
        max_depth=max_depth,
        max_string_bytes=max_string_bytes,
    )
    return value


def read_json(
    path: Path,
    *,
    require_object: bool = True,
    max_bytes: int = DEFAULT_MAX_JSON_BYTES,
    max_nodes: int = DEFAULT_MAX_NODES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_string_bytes: int = DEFAULT_MAX_STRING_BYTES,
) -> Any:
    try:
        with path.open("rb") as f:
            raw = f.read(max_bytes + 1)
    except OSError as exc:
        raise SafeIOError(f"cannot read {path}: {exc}") from exc
    if len(raw) > max_bytes:
        raise SafeIOError(f"{path}: JSON file exceeds byte limit ({max_bytes})")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SafeIOError(f"{path}: JSON must be valid UTF-8") from exc
    value = loads_json_strict(
        text,
        max_nodes=max_nodes,
        max_depth=max_depth,
        max_string_bytes=max_string_bytes,
    )
    if require_object and not isinstance(value, dict):
        raise SafeIOError(f"{path}: top-level JSON value must be an object")
    return value


def atomic_write_text(path: Path, text: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = -1
    tmp_name: str | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            os.fchmod(fd, mode)
        except (OSError, AttributeError):
            pass
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            fd = -1
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
        tmp_name = None
        # Best-effort directory fsync so rename survives a crash on POSIX filesystems.
        try:
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        if fd >= 0:
            os.close(fd)
        if tmp_name is not None:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass


def atomic_write_json(path: Path, value: Any, *, mode: int = 0o600) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", mode=mode)


@contextmanager
def advisory_lock(path: Path) -> Iterator[None]:
    """Process-level advisory lock for repository mutation.

    Uses ``fcntl`` on POSIX and a byte-range lock on Windows. Unsupported
    platforms fail closed. Direct library callers must acquire this lock.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    f = path.open("a+b")
    try:
        try:
            import fcntl  # type: ignore
        except ImportError:
            import msvcrt
            if path.stat().st_size == 0:
                f.write(b"\0")
                f.flush()
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            return
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    finally:
        f.close()
