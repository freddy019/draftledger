# v1.0.0 Final audit

Date: 2026-09-17. Scope: the supplied v1.0.0-rc2 source archive and the seven review areas in WORK_HANDOFF. No new product features were added. This is a local source/release audit, not an independent certification or a completed GitHub CI run.

## Findings and disposition

| Area | Findings addressed | Evidence |
| --- | --- | --- |
| Merge / rollback | Incoming decisions could miss destination-only premise changes; shortest-distance merge base could select an older ancestor; trust changes were omitted from material diffs. Revalidate both parents, use ancestry and reject ambiguous bases. Rollback remains append-only and explicitly historical. | Existing rollback test plus incoming-decision, trust-change, merge-base, delete/modify and no-commit-on-conflict regressions. |
| File writes / recovery | Windows lacked `fchmod` and locking. Failed switches moved metadata before validating targets. Checkpoint reads did not bind the content ID to the requested filename. | Real Windows concurrent CLI writes, identity substitution, failed switch, injected replace failure and checkpoint/metadata interruption tests. Recovery documented in hardening reference. |
| Trust boundary | Standalone retrieval ignored task exclusions and non-instruction authority escalation; compiler IDs could collide; external trusted control bypassed explicit review; multiline data could forge rendered sections. | Dedicated regression tests, existing multilingual injection corpus, lifecycle/scope/dependency tests. Rendered entries are quoted; structured fields remain authoritative. |
| JSON / compatibility | Numeric exponent overflow became infinity despite strict parsing. Non-finite output could be serialized. | Overflow and rejected-output regressions; protocol remains `1.0`; release audit validates schemas, examples and generated packets with jsonschema. |
| Claims / docs | READMEs still identified RC1; locking, crash recovery and rollback limitations were underspecified. | Updated bilingual release status, SKILL boundaries, security policy, release notes and operational documentation. |
| Fresh install | RC2 failed core output smoke flows on Windows. | Final verification logs accompany the local handoff; archive extraction and local clean-clone audit are required before delivery. Runtime smoke uses only the standard library. |
| Repository / packaging | Broad packaging could collect local root files or its own output; archive modes depended on platform. | Explicit release paths, symlink rejection, external archive destination, atomic archive replacement, repeatable archive test, expanded six-job CI matrix. |

## Verification record

The final regression suite contains 70 tests. On this Windows host, 69 pass and the POSIX-only output-symlink test is skipped. Development validation uses Python 3.12 and jsonschema 4.26.0. The full strict release audit includes compilation, CLI help, clean/broken examples, schema validation, revalidation apply/lint, context compilation/provenance, hardening and VCS smoke flows.

Machine output and archive checksum are retained outside the release source tree in the local delivery directory. The delivery is accepted only after full strict audit, deterministic rebuild comparison, fresh-extraction audit and local clean-clone verification succeed.

## Limits and publication gate

- Linux/macOS and Python 3.11/3.13 hosted jobs are configured, not locally executed. The POSIX symlink case must run there. All six CI jobs must pass before publishing the GitHub release tag.
- Atomicity applies per file. Fault injection covers replacement failure and interruption between checkpoint and metadata writes, not physical power loss on every filesystem. Optional exports can fail after commit.
- Mutating library callers must acquire the repository lock themselves. Caller-owned paths and trustworthy state metadata are preconditions; synchronized/network storage needs external coordination.
- Schema validation is a development/release check, not a complete runtime validator. Trust labels are assertions, not cryptographic attestations. Delimiter escaping and injection tests do not prove model obedience.
- Release packaging excludes unknown root files and known local/cache paths; maintainers must still review files placed inside approved release directories.
- Existing MIT terms are preserved. The supplied copyright line has only a year; confirm the rights holder before public publication.

No known unresolved code blocker remains within the exercised local scope. GitHub repository creation, hosted CI execution, owner/visibility choice and public release are subsequent publication steps, not claimed complete by this report.
