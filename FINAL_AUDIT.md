# v1.1.0 Final audit

Date: 2026-09-17. Scope: the v1.1 multi-thread and multi-agent handoff feature plus the complete existing release contract. This is a local source/release audit, not an independent certification or a completed GitHub-hosted CI run.

## Handoff invariants reviewed

| Area | Required behavior | Evidence |
| --- | --- | --- |
| Ownership | A work item has one current owner; another agent cannot update, complete, cancel, or release owned work. Active parent/child scopes cannot overlap. | Ownership and scope-collision tests plus two-process concurrent claim test. |
| Concurrency | Local writers serialize through the board lock; stale logical writers can pass an expected revision and fail before mutation. | Real concurrent CLI claim and stale-revision byte-preservation tests on Windows. |
| Recovery | Claims expire without silently changing ownership. Takeover is explicit and audited; blocked work can be explicitly reassigned. | Lease takeover, blocked-owner takeover, release, blocker resolution, and monotonic-time tests. |
| Dependencies | Downstream work cannot be claimed until every declared dependency is completed. Cycles, missing dependencies, self-dependencies, and duplicates are invalid. | Dependency gate and lint regression tests. |
| State coherence | A handoff can pin the canonical governed-state fingerprint; mismatch is visible before another work wave. Base refresh is refused while work is claimed or blocked. | Stale-state lint and active-work refresh rejection tests. |
| Trust boundary | Handoff text, another agent's progress, and outputs remain data. They do not create active instructions or approve integration. | Protocol, schema, templates, SKILL guidance, security docs, and existing control/data boundary suite. |
| Traceability | Claims, progress, blockers, resolution, completion, cancellation, and takeover append coordination events. | Lifecycle unit tests, clean example, schema validation, and release smoke flow. |
| Integration | Completion records a result and declared artifacts. Review, source-control integration, and semantic decision revalidation remain explicit. | Protocol reference and release documentation review. |

## Complete verification record

- Full strict release audit: 0 errors, 0 warnings.
- Unit suite: 83 tests; 82 passed on this Windows host and one POSIX-only output-symlink test was skipped.
- Handoff suite: 13 tests, including a real two-process claim race.
- Published JSON schemas, static examples, templates, and generated smoke artifacts validated with jsonschema 4.26.0 and format checking.
- Python compilation and CLI help checks passed for every shipped command.
- End-to-end handoff smoke: initialize, add work, register agent, claim, complete, and strict lint against governed state.
- Existing compiler, retrieval, provenance, revalidation, State VCS, hardening, release packaging, and prompt-injection regressions remained green.

The delivery is accepted only after the final source commit, audited build, fresh-extraction audit, clean local clone audit, dependency-free runtime smoke, and byte-identical archive rebuild succeed. Machine output and checksum are retained outside the release source tree.

## Compatibility

Package version advances from 1.0.0 to 1.1.0. State, context, and handoff document protocols use `version: "1.0"`. Existing v1.0 state needs no migration; the handoff board is optional. Runtime tools remain standard-library only. Development schema validation uses `requirements-dev.txt`.

## Limits and publication gate

- The process lock coordinates writers on one host. File-sync and network filesystems with weak locking require an external transaction service.
- Agent IDs, thread references, events, hashes, and trust labels are not authenticated or cryptographically signed. A process that can rewrite repository files can forge them.
- Expired leases do not transfer ownership automatically. A new agent must inspect artifacts and explicitly take over. Blocked work has no running lease and requires explicit `resume --take-over` if its owner disappears.
- Expected revisions are optional for interactive convenience. Concurrent agents should always provide the last revision they observed.
- Atomicity applies per board file. It does not make the board, source tree, governed state, and external systems one transaction.
- Output paths are declarations. The handoff tool does not prove that artifacts exist, are safe, or satisfy acceptance criteria.
- Linux/macOS and Python 3.11/3.13 hosted jobs are configured but not locally executed. All six GitHub CI jobs must pass before publishing the release tag.
- Existing MIT terms are preserved. The supplied copyright line has only a year; confirm the rights holder before public publication.

No known unresolved code blocker remains within the exercised local scope. GitHub repository creation, hosted CI execution, owner/visibility choice, and public release remain subsequent publication steps.
