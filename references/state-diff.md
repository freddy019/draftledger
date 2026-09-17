# State Diff and Dependency Revalidation

Long-running work needs more than a current snapshot. When state changes, the agent must know which conclusions were derived from the old state.

`State Diff` compares two governed-state snapshots and separates ordinary edits from changes that can invalidate reasoning.

## Why this exists

A decision can remain syntactically valid while its premises have changed.

Example:

1. `F-001`: default selling price is 168.
2. `D-004`: use 168 as the baseline for the margin model.
3. The user later replaces the price with 158.
4. `F-001` becomes superseded and `F-002` becomes active.

Without dependency revalidation, `D-004` may silently survive and continue contaminating later work.

## Material upstream changes

A decision should be reconsidered when a fact, assumption, or instruction it depends on is materially changed, removed, or becomes invalid.

Typical invalidators:

- fact: `active -> superseded` or `active -> disputed`;
- assumption: `active -> rejected` or `active -> expired`;
- instruction: `active -> superseded`, `expired`, or `revoked`;
- meaning-bearing fields such as statement, scope, priority, or instruction text change.

Adding a new fact does not automatically invalidate a decision unless it changes one of that decision's dependencies.

## Revalidation protocol

When a dependency changes:

1. Identify every active decision that references the changed item.
2. Mark those decisions `needs_review` or otherwise block silent reuse.
3. Preserve the original decision and rationale.
4. Re-evaluate the decision against current active facts, assumptions, and instructions.
5. Either:
   - restore it to `active` with a new validation record;
   - supersede it with a replacement decision; or
   - reverse it.

Do not delete the old decision merely because its premises changed. The lineage is useful evidence.

## CLI

```bash
python scripts/state_diff.py before.json after.json
python scripts/state_diff.py before.json after.json --json
python scripts/state_diff.py before.json after.json --fail-on-review
python scripts/state_diff.py before.json after.json \
  --write-review-state .agent-state/state.review.json
```

`--write-review-state` creates a copy of the current state and marks affected active decisions as `needs_review`. It does not overwrite the input file.

## Design rule

**State mutation and decision validity are separate concerns.**

Changing a premise is allowed. Silently continuing to trust every conclusion derived from that premise is not.
