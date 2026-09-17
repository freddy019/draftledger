# Security regression material

This directory contains small, non-executable adversarial corpora used by the test suite.

The payloads are **data**, not instructions. Their purpose is to verify DraftLedger's trust-boundary invariant:

> Data must never become instruction merely because it entered context.

Security scope is intentionally narrow: this project can harden its own state files, compiler, provenance manifests, and version-control metadata. It does not claim to inspect hidden platform prompts, sandbox boundaries, or model internals.
