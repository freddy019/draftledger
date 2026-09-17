# Security Policy

Agent State Governance treats context assembly and governed state as a security boundary, but it does **not** claim to sandbox a model, inspect hidden host prompts, or make untrusted model output safe by itself.

## Supported versions

Security fixes target the latest stable 1.x release. Release candidates and earlier development snapshots are not supported after v1.0.0.

## Security invariants

The project is designed around these invariants:

- data does not become control merely because it contains imperative text;
- externally sourced instructions require explicit review before receiving control authority;
- stale or superseded control state must not be silently reactivated;
- machine-readable inputs are parsed with bounded, strict JSON handling;
- state mutations use atomic replacement where the host filesystem supports it;
- State VCS checkpoints are content-addressed and verified before use;
- deterministic checks never substitute for semantic review of a decision.

See `references/trust-boundary.md` and `references/hardening.md` for the detailed threat model.

## Reporting a vulnerability

After the repository is published on GitHub, prefer GitHub Private Vulnerability Reporting / Security Advisories if enabled. Do not put exploit details, secrets, tokens, or sensitive project state in a public issue.

A useful report should include the affected version, minimal reproduction steps, expected behavior, actual behavior, and the security impact. Please distinguish a model-quality failure from a boundary violation in the deterministic tooling.

## Out of scope

The project cannot inspect or govern opaque system prompts, host-side memory, platform routing, model weights, external sandbox configuration, or context that the host does not expose. It also cannot prove that a language model followed the compiled context; it can only make the declared inputs auditable.
