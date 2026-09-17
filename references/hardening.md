# Hardening and threat model

DraftLedger treats state management as a security boundary, not only a convenience layer.

## Threats in scope

- malformed, duplicated, deeply nested, oversized, or non-finite JSON;
- resource exhaustion from pathological state documents;
- stale or unauthorized control state;
- stored prompt injection in facts, files, tool output, retrieval results, or summaries;
- summary provenance cycles;
- corrupted immutable checkpoints;
- branch-name/path traversal attempts;
- concurrent State VCS mutations that would otherwise lose updates;
- partial writes or process failure during file replacement;
- silent semantic-state corruption after merge or revalidation.
- lost updates, duplicate ownership, stale writers, and abandoned claims during multi-agent handoff.

## Threats out of scope

- hidden system/developer prompts that the host does not expose;
- compromise of the Python interpreter, operating system, or model provider;
- malicious code execution supplied by another plugin or host tool;
- confidentiality guarantees for storage outside this project's files.

## Hardened JSON I/O

All CLI state readers use `scripts/safe_io.py`.

The parser rejects:

- duplicate object keys;
- `NaN`, `Infinity`, and `-Infinity`;
- invalid UTF-8;
- files larger than the configured limit;
- excessive nesting, node count, or individual string size.

Writes use a same-directory temporary file, flush + `fsync`, and atomic `os.replace`. This avoids exposing half-written JSON after a process crash. On POSIX, replacement also avoids following a pre-existing output symlink to another target file.

## State VCS concurrency

Mutating CLI operations acquire a repository advisory lock before reading/updating branch metadata. Checkpoints remain content-addressed and immutable. Integrity is verified by both checkpoint ID and state hash on read.

The lock is process-level coordination, not a distributed lock. Network filesystems with weak locking semantics require additional host-level coordination.

The Handoff Board uses the same local lock and atomic replacement. It also uses a monotonically increasing revision for optimistic concurrency. A caller acting on a previously read board should pass `--expected-revision`; a mismatch fails before mutation. Leases make abandoned claims visible but do not transfer ownership automatically. Another agent must explicitly take over an expired claim or blocked item, leaving an event in the board.

## Prompt injection boundary

Retrieved or imported text remains data. Control-like phrases in Facts, Assumptions, Decisions, Open Items, files, web pages, or retrieval results do not gain instruction authority.

Only the governed `instructions` registry may carry `authority: control`, and active control must pass scope, lifecycle, and trust checks. `scripts/hardening_check.py` surfaces control-like text found in the data plane as an informational attack-surface finding and warns about externally sourced control marked trusted without an explicit review boundary.

## Hardening check

```bash
python scripts/hardening_check.py examples/sample-state.json --strict
```

An optional declared Context Manifest can be checked at the same time:

```bash
python scripts/hardening_check.py examples/sample-state.json \
  --manifest /tmp/context-manifest.json --strict
```

The hardening check composes Context Lint and Context Trace findings; it is not a replacement for either tool.

## Release discipline

Before any public release:

1. run the full unit suite;
2. run deterministic fuzz/regression tests;
3. run clean-state hardening checks;
4. run the prompt-injection corpus;
5. exercise concurrent VCS mutation;
6. compile every Python module;
7. perform a fresh-install smoke test in a clean directory;
8. manually review security-sensitive diffs and documented invariants.

Passing these checks reduces known failure modes; it is not proof that the software is vulnerability-free.

## v1.0 operational limits and recovery

CLI mutation locks use POSIX `flock` or Windows byte-range locking. Windows contention exceeding the platform retry window fails without mutation; retry the command after the competing writer completes. Library functions do not implicitly lock: callers must hold `advisory_lock(repo / ".lock")` around each complete read-modify-write operation.

Checkpoint storage completes before the single atomic metadata replacement. If a process exits between these writes, the old head stays authoritative and an unreferenced checkpoint may remain. Preserve it for inspection; rerun the intended operation against the current head. Never delete or rewrite referenced checkpoints to recover. A failed optional state export can occur after a successful commit: inspect `log` and use `restore` to regenerate the file before retrying a mutation. Multiple exported files are not one atomic transaction.

Temporary files may survive abrupt process termination before cleanup. They are not authoritative state. After confirming no writer is active, inspect them before removing them. Atomic replacement is not a guarantee against power loss on every filesystem; directory fsync is best effort and Windows ACLs remain host-managed.

The repository directory, its ancestor directories, output paths and state trust metadata must be controlled by the caller. These tools do not sandbox paths, defend against hostile directory replacement, or authenticate a self-declared `reviewed` value. Do not store a concurrently used repository on a synchronizing/network filesystem without external coordination. Checkpoint hashes detect accidental or uncoordinated corruption, not an attacker able to rewrite all hashes and metadata.

External control (`web`, `file`, `tool`, `import`, `retrieval`) must be explicitly `reviewed` before the compiler accepts it. Rendered entries and labels escape line breaks and control characters. This protects structural delimiters; it does not prove a model will obey them. Retriever producer/method and rejection diagnostics are untrusted diagnostic metadata, not executable context.

The CLI validates protocol versions and relevant semantic invariants; it is not a complete runtime JSON Schema validator. Validate externally authored documents against the published schemas before using the tools. Full strict release audit validates shipped examples and generated packets with jsonschema.
