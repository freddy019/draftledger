# Context Compiler

The Context Compiler builds the smallest practical reasoning context from governed state for one task.

Its purpose is prevention rather than cleanup: do not pass the entire project memory to the model when only a small, current subset is relevant.

## Invariant

**Compile from active governed state, not from accumulated prose history.**

A compiler must never reactivate stale state merely because old text is lexically relevant.

## Selection order

The bundled compiler uses a conservative deterministic policy:

1. Explicit task `require_ids`.
2. Active instructions applicable to the current scope.
3. Active items with lexical overlap with the task objective.
4. Dependency closure for selected Decisions.
5. Budget trimming of optional items only.

Inactive facts, rejected assumptions, superseded instructions, reversed decisions, and closed items are excluded from normal compilation.

## Why deterministic first

Semantic retrieval can improve recall, but it also adds another opaque model decision to the context pipeline. A deterministic baseline makes selection auditable. Hosts may add embeddings or model-assisted retrieval later, but those candidates should still pass the same lifecycle checks before inclusion.

## Protected context

Explicitly required IDs and applicable active instructions are protected from budget trimming. If protected context alone exceeds the configured budget, compilation fails instead of silently dropping control state.

## Decision closure

A selected Decision is not meaningful without its premises. The compiler therefore adds the active Facts, Assumptions, and Instructions listed in its dependency fields.

This does not validate the Decision. Revalidation remains a separate workflow.

## Output

`scripts/context_compile.py` can emit:

- rendered reasoning context;
- a full compiler packet with selection rationale and omissions;
- a Context Manifest compatible with `context_trace.py`.

The recommended pipeline is:

```text
Governed State
     ↓
Context Compiler
     ↓
Context Manifest + bounded reasoning context
     ↓
Context Trace / Lint
     ↓
Model reasoning
     ↓
State update
```

## Visibility boundary

The compiler governs context supplied by the host or agent. It cannot remove or inspect opaque platform/system prompts that the runtime does not expose.
