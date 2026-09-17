# State Version Control

Long-running agent work often needs more than one valid state at a time. A pricing project may need a conservative scenario and an aggressive scenario; a research task may need competing hypotheses; a product plan may need an experimental branch that must not contaminate the main state.

`state_vcs.py` provides a lightweight, append-only version-control layer for governed state.

It is intentionally separate from Git. Git versions files. State VCS versions the semantic control plane that drives agent reasoning.

## Operations

### Initialize

```bash
python scripts/state_vcs.py init .agent-state/state.json
```

This creates `.agent-state/vcs/`, an immutable first checkpoint, and a `main` branch.

### Checkpoint

```bash
python scripts/state_vcs.py checkpoint .agent-state/state.json \
  -m "confirmed new refund assumption"
```

A checkpoint is content-addressed and append-only. Existing checkpoints are never rewritten.

### Branch

```bash
python scripts/state_vcs.py branch scenario-b
python scripts/state_vcs.py switch scenario-b --output .agent-state/state.json
```

Use branches for competing assumptions, alternative plans, or experiments whose state should remain isolated.

### Diff

```bash
python scripts/state_vcs.py diff main scenario-b
```

Ref-to-ref diff reuses the State Diff rules and reports downstream decisions that would require revalidation.

### Rollback

```bash
python scripts/state_vcs.py rollback C-123456789abc \
  --output .agent-state/state.json
```

Rollback is deliberately append-only. It does not move the branch pointer backward or erase newer checkpoints. Instead it creates a new checkpoint whose state is restored from the selected historical checkpoint.

This makes rollback itself reversible and auditable.

### Merge

```bash
python scripts/state_vcs.py merge scenario-b \
  --output .agent-state/state.json \
  --conflicts .agent-state/merge-conflicts.json
```

Merge is a three-way merge using the nearest common checkpoint as the merge base.

The merger is ID-aware for the five governed registries. Independent field changes can merge automatically. Changes to the same field produce an explicit conflict rather than choosing a winner silently.

After a clean merge, changed facts, assumptions, and instructions are traced into Decision dependencies. Any affected Decision is marked `needs_review` before the merge checkpoint is committed.

A syntactically clean merge is therefore not treated as semantic validation.

## Repository shape

```text
.agent-state/vcs/
├── meta.json
└── checkpoints/
    ├── C-....json
    └── C-....json
```

`meta.json` stores only branch heads and the current branch. Each checkpoint stores:

- checkpoint ID;
- timestamp;
- message;
- one or more parent checkpoints;
- state hash;
- complete governed state snapshot;
- operation metadata such as merge or rollback provenance.

Merge checkpoints have two parents.

## Core invariants

1. Checkpoints are immutable.
2. Rollback never deletes history.
3. Branches isolate alternative task states.
4. Merge conflicts are explicit.
5. A clean structural merge does not imply a valid Decision.
6. Premise changes introduced by a merge trigger dependency revalidation.
7. Conversation history remains evidence; checkpointed governed state remains the control plane.

## When to branch

Branch when the agent is about to explore an alternative that would otherwise mutate important shared state, especially when:

- several business scenarios must be compared;
- a hypothesis is speculative;
- a user asks to "try this without changing the current plan";
- an agent wants to test a new instruction set;
- an experimental conclusion should not contaminate the main decision history.

Do not create branches for every minor edit. Branches are for meaningful alternative states, not ordinary incremental updates.

## Final release edge cases

Merge bases follow ancestry, not shortest path distance. Multiple best bases in criss-cross history are rejected without mutation; reconcile that history explicitly. Post-merge review checks both input parents, so an incoming decision cannot silently reuse a premise changed only on the destination branch. Rollback intentionally restores the historical snapshot, including its lifecycle flags; it is not a claim that historical facts remain valid today. Run a new context audit before relying on restored state.

See [crash recovery and locking limits](hardening.md) before coordinating concurrent writers or recovering an interrupted export.
