# Changelog

## v1.0.0 — 2026-09-17

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

## v1.0.0-rc2

- Fixed a release-audit self-contamination bug where Python syntax checks generated `__pycache__` files that the same strict audit then reported as worktree junk.
- Python compile checks now emit bytecode only into an isolated temporary directory.
- All release-audit subprocesses run with bytecode generation disabled so verification does not mutate the source tree.
- Release builds now require `--full --strict` audit success before packaging.
- Re-ran the complete release-candidate test and audit flow from a clean extracted tree.

## v1.0.0-rc1

- Froze the public machine-readable protocol at `1.0` for the first stable release line.
- Added explicit protocol-version rejection so older/future documents do not silently pass through v1 tooling.
- Added OpenAI `agents/openai.yaml` metadata while keeping `SKILL.md` compatible with the Agent Skills specification.
- Added `scripts/release_audit.py` for skill-format, schema, CLI, smoke-flow, and optional full-test validation.
- Added deterministic `scripts/build_release.py` with SHA-256 sidecar generation and cache/local-state exclusion.
- Added `SECURITY.md`, `CONTRIBUTING.md`, `VERSION`, development schema validation, and release-audit documentation.
- Hardened bounded JSON reads against stat/read time-of-check/time-of-use races by reading from one descriptor with a hard byte cap.
- Fixed `templates/state.json` so the shipped template validates before user edits.
- Added release-candidate documentation and CI release-audit coverage.

## v0.9.0

- Added shared strict/bounded JSON I/O in `scripts/safe_io.py`.
- Reject duplicate JSON keys, non-finite numbers, invalid UTF-8, excessive file size, excessive nesting, excessive node count, and oversized strings.
- Switched machine-readable outputs to same-directory atomic writes with flush + `fsync` + `os.replace`.
- Added POSIX advisory locking around mutating State VCS CLI operations to prevent lost updates from concurrent processes.
- Added summary-provenance cycle detection to Context Trace.
- Added `scripts/hardening_check.py` to compose state invariants, trust-boundary checks, and optional Context Trace findings.
- Added multilingual prompt-injection regression corpus and explicit control-like-data detection.
- Added checkpoint-tamper, branch traversal, concurrent-write, symlink replacement, malformed JSON, resource-limit, and deterministic fuzz tests.
- Added `references/hardening.md` with a scoped threat model and pre-1.0 release checklist.
- No new third-party dependencies.

## v0.8.0

- Added a formal control/data trust boundary for governed context.
- Added `authority`, `trust_level`, and `origin` provenance metadata to state items.
- Added fail-closed handling for untrusted or unauthorized active instructions.
- Prevented task exclusions from suppressing applicable active control instructions.
- Added proposal-only semantic retrieval through `--semantic-candidates`.
- Added `scripts/retrieval_gate.py` so embedding/LLM retrievers can nominate governed IDs without gaining instruction authority.
- Semantic candidates are limited to existing state IDs plus bounded scores; retriever free text is never promoted into reasoning context.
- Split compiled output into explicit `CONTROL PLANE` and `DATA PLANE` sections.
- Extended Context Trace with authority, trust, and plane mismatch checks.
- Added semantic-candidate and retrieval-gate schemas, security-focused tests, docs, and CI coverage.
- Documented the invariant: **data must never become instruction merely because it entered context**.

## v0.7.0

- Added deterministic `Context Compiler` with `scripts/context_compile.py`.
- Added task-scoped context selection from active governed state instead of whole-history prompting.
- Added scope-aware inclusion of active Instructions.
- Added lexical relevance ranking as an auditable baseline retrieval policy.
- Added automatic dependency closure for selected Decisions.
- Added hard context budgets with protected control-state semantics.
- Added fail-closed behavior when required/protected state cannot fit the configured budget.
- Added compiler output provenance compatible with Context Trace.
- Added `compiled-context.schema.json`, task example, tests, documentation, and CI coverage.
- Documented that semantic retrieval may extend the compiler later, but lifecycle validation remains mandatory.

## v0.6.0

- Added declared context provenance with `scripts/context_trace.py`.
- Added Context Manifest generation for material state influences.
- Added stale-context detection for inactive facts, assumptions, instructions, decisions, and open items.
- Added instruction shadowing detection when superseded prompt state remains in context beside its active replacement.
- Added snapshot hashing to detect in-place state mutation after context assembly.
- Added summary provenance and taint propagation across summary-of-summary chains.
- Added explicit `unmanaged` context entries so host/manual residue becomes visible instead of implicit.
- Added `context-manifest.schema.json`, examples, tests, documentation, and CI coverage.
- Documented the visibility boundary: opaque platform/system prompts cannot be introspected by this tool.

## v0.5.0

- Added append-only governed-state version control with `scripts/state_vcs.py`.
- Added immutable content-addressed checkpoints and branch refs.
- Added reversible rollback that creates a new checkpoint instead of rewriting history.
- Added ref-to-ref semantic diff using existing State Diff rules.
- Added ID-aware three-way merge with explicit same-field conflict reporting.
- Added merge ancestry and nearest common-base resolution.
- Added automatic Decision revalidation marking when a merge changes supporting premises.
- Added `references/version-control.md`, unit tests, and CI smoke coverage.
- Documented the invariant that a clean merge is not semantic validation.

## v0.4.0

- Added explicit decision revalidation workflow with `scripts/revalidate.py`.
- Added lineage-aware review planning for stale facts, assumptions, and instructions.
- Added four explicit outcomes: `revalidated`, `superseded`, `reversed`, and `blocked`.
- Added guarded resolution application so stale dependencies cannot be silently reactivated.
- Added `validation_history` provenance and optional blocker creation.
- Added revalidation plan/resolution schemas, examples, tests, and CI coverage.
- Documented the core invariant: dependency replacement is not decision validation.

## v0.3.0

- Added `State Diff` for comparing governed-state snapshots.
- Added dependency revalidation for decisions whose supporting facts, assumptions, or instructions changed.
- Added `--write-review-state` to mark affected decisions as `needs_review` without overwriting source state.
- Added review provenance fields to the JSON Schema.
- Added diff examples, documentation, and unit tests.

## v0.2.0

- Added optional machine-readable governed state in JSON.
- Added `Context Lint`, a dependency-free semantic invariant checker.
- Added instruction `key` and `scope_id` for deterministic conflict detection.
- Added checks for stale decision dependencies and invalid assumption dependencies.
- Added JSON Schema, clean/broken examples, and unit tests.
- Clarified that Context Audit and Context Lint solve different problems.

## v0.1.0

- Initial methodology-first release.
- Added typed facts, assumptions, instructions, decisions, and open items.
- Added instruction lifecycle, compression policy, and Context Audit.
