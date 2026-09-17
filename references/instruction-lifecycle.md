# Instruction Lifecycle

Instructions are not immortal.

A long-running task commonly accumulates dozens of directives that were valid only for one phase, one deliverable, or one temporary experiment. Without lifecycle management, these directives become prompt residue.

## Lifecycle states

- `active` — currently binding within its scope.
- `superseded` — replaced by a newer instruction.
- `expired` — its time or condition has ended.
- `revoked` — explicitly withdrawn by the user or authorized controller.

## Scope

Use the narrowest accurate scope:

- `global` — applies broadly across the project or workspace.
- `project` — applies to one project.
- `task` — applies to one task or deliverable.
- `step` — applies only to a local operation.

A step-scoped instruction must not silently become a project preference.

## Conflict resolution

When two active instructions conflict:

1. Compare authority.
2. Compare scope relevance.
3. Compare explicitness.
4. Compare recency within the same authority and scope.
5. If still ambiguous, surface the conflict.

Do not blend incompatible instructions into a compromise unless the user asks for one.

## Supersession

Prefer lineage over deletion.

Example:

```text
I-004: Price calculations use 228 by default. [superseded]
I-011: Price calculations use 168 by default. [active]
I-011 supersedes I-004.
```

The old item remains useful for understanding prior decisions, but must not influence new calculations.

## Contamination check

An instruction is a contamination risk when it is:

- superseded but still repeated in summaries;
- task-scoped but being applied project-wide;
- inferred rather than explicitly requested;
- no longer relevant to the current phase;
- contradicted by a newer user instruction.

Surface these items during Context Audit.
