# Revalidation Workflow

`State Diff` can prove that a decision's premises changed. It cannot prove that the old conclusion is still valid.

That distinction is the core of revalidation.

## Rule

**Dependency replacement is not decision validation.**

If `F-001` is superseded by `F-002`, an agent may suggest `F-002` as a candidate dependency, but it must not reactivate a decision merely by swapping IDs. The conclusion itself must be reconsidered under current state.

## Workflow

1. `state_diff.py` marks affected decisions as `needs_review`.
2. `revalidate.py plan` inspects each decision and resolves deterministic lineage:
   - superseded fact -> candidate active fact;
   - confirmed assumption -> candidate promoted fact;
   - superseded instruction -> candidate active instruction;
   - rejected/expired/missing premise -> blocker.
3. An agent or human performs semantic review and selects one outcome:
   - `revalidated` — the same decision still holds under current premises;
   - `superseded` — a materially different decision replaces it;
   - `reversed` — the old decision should no longer be followed;
   - `blocked` — current evidence is insufficient to resolve it.
4. `revalidate.py apply` validates dependency status, records provenance, and performs the lifecycle transition.
5. Run `context_lint.py` on the resulting state.

## Commands

```bash
python scripts/state_diff.py before.json after.json \
  --write-review-state state.review.json

python scripts/revalidate.py plan state.review.json \
  --output revalidation-plan.json

python scripts/revalidate.py apply state.review.json resolution.json \
  --output state.revalidated.json

python scripts/context_lint.py state.revalidated.json --strict
```

## Outcome semantics

### Revalidated

Use only when the *same decision statement* remains valid. Dependencies may be updated to current active items, but the conclusion itself should not be rewritten in place.

This preserves decision identity.

### Superseded

Use when the conclusion materially changes. Create a new decision ID. The old decision becomes `superseded` and points to the replacement through `superseded_by`.

### Reversed

Use when the conclusion is explicitly no longer valid and there is no replacement decision that should inherit its role.

### Blocked

Use when missing or rejected premises prevent a justified conclusion. The decision remains `needs_review`, and the apply tool can create an open blocker item so the unresolved state is visible rather than silently forgotten.

## Why not auto-revalidate?

Automatic ID migration is tempting but unsafe. A price changing from 168 to 158 may preserve one strategic decision and invalidate another. The dependency graph can tell us *where to look*, not *what the new answer must be*.

The deterministic layer should therefore handle lineage, status, and invariants. Semantic judgment remains an explicit review step.
