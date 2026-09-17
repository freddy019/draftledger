# Agent State Governance v1.1.0

v1.1.0 adds a governed relay file for multi-thread and multi-AI work. A project can now keep a machine-readable `.agent-state/handoff.json` beside governed state and coordinate independent work without relying on prose summaries or chat history.

The handoff board records:

- explicit work items, scopes, acceptance criteria, inputs, dependencies, and outputs;
- one current owner per work item;
- expiring leases with explicit, audited takeover;
- optimistic revisions that reject stale writers;
- progress, blockers, resolution, completion, and append-only coordination events;
- an optional governed-state fingerprint for detecting stale work plans.

The new `scripts/handoff.py` CLI uses the same strict JSON handling, local process locking, and atomic writes as State VCS. A Markdown template provides human orientation, while the JSON board remains authoritative for claims and revisions. Handoff content is data-plane material and cannot authorize itself as an instruction. Completion records a result; review and integration remain explicit.

## Compatibility

Python 3.11+; no third-party runtime dependencies. Package version is `1.1.0`; the state, context, and new handoff document protocols remain `1.0`. Existing v1.0 governed state needs no migration. Projects that do not need parallel coordination can omit the handoff files.

The lock coordinates processes on one host. Cross-machine writers on synchronized or network filesystems still require an external transaction service. Work leases do not transfer ownership automatically.

## Verification

See [FINAL_AUDIT.md](FINAL_AUDIT.md) for executed checks and platform limits. The v1.1.0 ZIP and SHA-256 sidecar are prepared locally after final verification. GitHub publication has not been performed.
