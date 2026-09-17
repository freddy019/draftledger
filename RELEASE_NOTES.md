# DraftLedger v0.1.0-alpha.1

DraftLedger preserves the process that a finished artifact cannot reconstruct: verified facts, working assumptions, active instructions, decisions and their rationale, rejected directions, unresolved questions, and ownership across AI threads.

This first public alpha is aimed at long-running creative and knowledge projects such as copywriting, content planning, novels, scripts, worldbuilding, research synthesis, consulting reports, strategy, naming, and UX writing.

## Included

- Typed governed state with lifecycle-aware facts, assumptions, instructions, decisions, and open items.
- Context compilation, provenance tracing, contamination detection, semantic-retrieval gating, and a strict control/data boundary.
- State diff, explicit decision revalidation, and append-only local state version control.
- A machine-readable handoff board for multi-thread and multi-agent work, including claims, leases, takeovers, scope collision checks, dependencies, progress, blockers, cancellation, and completion.
- Strict bounded JSON parsing, atomic writes, advisory locking, deterministic tests, release auditing, and reproducible ZIP packaging.

## Alpha notice

Expect defects and breaking changes. Public schemas, commands, and workflows may change without backward-compatibility guarantees before v1.0. Do not run this preview unattended in critical production workflows.

The package version is `0.1.0-alpha.1`. Machine-readable state, context, and handoff documents currently use `version: "1.0"` as an internal format identifier retained from development; that identifier is not a public stability promise.

Runtime: Python 3.11+ with no third-party runtime dependencies. `jsonschema` is used only by development and release verification.

See [FINAL_AUDIT.md](FINAL_AUDIT.md) for verification evidence and [SECURITY.md](SECURITY.md) for the trust boundary and known limits.
