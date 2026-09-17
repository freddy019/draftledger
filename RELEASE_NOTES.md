# Agent State Governance v1.0.0 Final

- Finalized the stable release without adding new product features; protocol stays at `1.0`.
- Fixed Windows atomic writes and added Windows process locking for mutating VCS CLI operations.
- Reject numeric overflow to infinity and non-finite output values.
- Verify checkpoint identity against its requested filename; validate heads before branch/checkpoint mutation and validate switch targets before changing metadata.
- Determine merge bases by ancestry; reject ambiguous criss-cross bases. Revalidate merged decisions against both parents, including trust/provenance changes.
- Reject duplicate compiler IDs and external control without reviewed trust. Apply task exclusions and authority checks in the standalone retrieval gate.
- Quote rendered entries and task/project labels so embedded newlines cannot forge context sections.
- Restrict release inputs, reject symlinks and in-tree archive destinations, and replace archives atomically.
- Keep audit intermediates outside the repository, add 17 final-audit regression cases, and configure Linux/Windows/macOS CI on Python 3.11 and 3.13.
- Document crash recovery, library locking responsibilities, trust limits, final verification, and GitHub publication steps.

## Compatibility

Python 3.11+; no third-party runtime dependencies. State, manifest, retrieval and compiler protocols remain `1.0`; no migration is required for valid RC2 documents. Development schema checks use `requirements-dev.txt`.

Inputs previously accepted despite ambiguity or invalid trust may now fail closed. Rendered context entries are JSON-quoted single lines; consumers should use the structured packet fields instead of parsing display prose.

## Verification

See [FINAL_AUDIT.md](FINAL_AUDIT.md) for executed checks and platform limits. ZIP and SHA-256 sidecar are prepared locally. GitHub publication has not been performed.
