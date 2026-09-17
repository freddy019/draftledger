# Context Provenance and Contamination Detection

Long-running agents can have a perfectly clean governed state and still reason from stale material if an old summary, handoff, memory fragment, or superseded instruction is still present in the *assembled reasoning context*.

v0.6 introduces a declared **Context Manifest**. It records what materially entered a reasoning step and where it came from.

## Visibility boundary

This mechanism does **not** claim to inspect hidden platform prompts, model internals, or opaque host context. It can only audit context that the agent or host declares in the manifest. Treat it as provenance for the controllable context plane.

## Entry kinds

A context entry is one of:

- `state` — a governed Fact, Assumption, Instruction, Decision, or Open Item;
- `summary` — compressed prose with explicit `derived_from` lineage;
- `unmanaged` — host/manual context whose lifecycle is not governed.

State entries carry a `snapshot_hash`. This lets the tool detect a subtle failure mode: an ID stays the same while the content or lifecycle status changes.

## Core contamination checks

`context_trace.py lint` detects:

- missing context sources;
- inactive state items still included in context;
- stale instruction shadowing, where a superseded instruction remains present while its active replacement exists;
- snapshot hash mismatch after in-place mutation;
- summaries derived from missing or inactive sources;
- taint propagation through summary-of-summary chains;
- unmanaged context whose lifecycle cannot be verified.

A stale summary is not automatically deleted. It is marked as tainted so the agent or human can rebuild it from current state.

## Commands

Build a manifest from explicitly selected state items:

```bash
python scripts/context_trace.py build .agent-state/state.json \
  --ids F-001 A-001 I-009 D-001 \
  --output .agent-state/context-manifest.json
```

If `--ids` is omitted, all currently active state items are selected.

Lint the declared context:

```bash
python scripts/context_trace.py lint \
  .agent-state/state.json \
  .agent-state/context-manifest.json \
  --strict
```

Explain the current influence set:

```bash
python scripts/context_trace.py explain \
  .agent-state/state.json \
  .agent-state/context-manifest.json
```

## Why this is separate from Context Lint

`Context Lint` asks: **is governed state internally valid?**

`Context Trace` asks: **is the context currently feeding reasoning actually drawn from valid state?**

Both are needed. A clean database does not guarantee a clean query result if the application is still serving an old cache.

## Operational rule

Before a high-impact answer, handoff, or major phase transition:

1. compile or update the context manifest;
2. lint it against current governed state;
3. rebuild tainted summaries;
4. remove or explicitly justify unmanaged context;
5. only then reason from the assembled context.

This makes context provenance inspectable instead of implicit.
