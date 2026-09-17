# Context Lint

`Context Audit` is semantic and agent-driven. `Context Lint` is deterministic and machine-checkable.

Use both:

- **Audit** asks whether the current state still makes sense.
- **Lint** asks whether the state violates structural or lifecycle invariants.

## What the linter checks

The bundled `scripts/context_lint.py` uses only the Python standard library and checks:

- duplicate IDs;
- dangling state references;
- instruction supersession cycles;
- instructions marked active while also superseded;
- multiple active instructions for the same `key + scope + scope_id`;
- active decisions that depend on superseded facts;
- active decisions that depend on rejected or expired assumptions;
- active decisions that reference stale or missing instructions;
- confirmed assumptions that were never promoted to a fact;
- active assumptions with no validation condition.

## Instruction keys

`key` is optional but strongly recommended for instructions that control a single mutable setting.

Example:

```json
{
  "id": "I-009",
  "key": "default-price",
  "instruction": "Use 168 as the default price.",
  "scope": "project",
  "scope_id": "pricing-project",
  "status": "active"
}
```

If both I-002 and I-009 are active with the same key and scope, the linter reports an `ACTIVE_INSTRUCTION_COLLISION` instead of allowing the agent to silently choose one.

## Running

```bash
python scripts/context_lint.py .agent-state/state.json
```

For CI, treat warnings as failures too:

```bash
python scripts/context_lint.py .agent-state/state.json --strict
```

For tooling integrations:

```bash
python scripts/context_lint.py .agent-state/state.json --json
```

## Limits

Lint is intentionally conservative. It cannot reliably determine whether two natural-language instructions are semantically contradictory unless they share a declared `key`. It also cannot infer that a prose summary has changed meaning without a separate extraction or comparison step.

Do not pretend deterministic validation can replace semantic audit.
