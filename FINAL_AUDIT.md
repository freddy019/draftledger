# DraftLedger v0.1.0-alpha.1 final audit

Audit date: 2026-09-17

## Result

The local release candidate passed the strict release gate with **0 errors and 0 warnings**.

- Unit tests: **83 run, 82 passed, 1 skipped**. The skipped case exercises POSIX advisory-lock behavior and is not applicable on Windows.
- Skill metadata and OpenAI agent metadata: passed.
- JSON syntax, schemas, templates, and examples: passed.
- Python compilation and CLI help checks: passed.
- End-to-end smoke workflow: passed.
- Markdown link and repository hygiene checks: passed.
- Clean extracted-package audit: passed.
- Deterministic rebuild comparison: passed.

## Commands

```bash
python scripts/release_audit.py --full --strict
python scripts/build_release.py
```

The release archive is reproducible and accompanied by a SHA-256 sidecar. GitHub Actions repeats the strict audit on the supported Python matrix before a tag is released.

## Scope and limits

DraftLedger v0.1.0-alpha.1 is an experimental public preview. The audit verifies the published deterministic tooling and declared data contracts; it does not prove language-model correctness, inspect hidden platform prompts, authenticate collaborating agents, or protect a repository from a hostile process with write access.

Handoff leases coordinate cooperative writers on one adequately locked filesystem. They are not distributed consensus and should not be relied on across weakly consistent file-sync or network storage.

Machine-readable documents currently carry `version: "1.0"` as an internal format identifier. Public compatibility is not guaranteed during the alpha series.
