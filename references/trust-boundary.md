# Trust Boundary

DraftLedger separates **control** from **data**. This is a security boundary, not a formatting preference.

> Data must never become instruction merely because it entered context.

## Authority

Every governed state item carries an `authority`:

- `control` — executable project instruction. Reserved for the `instructions` registry.
- `data` — evidence or model input. Used by facts and assumptions.
- `advisory` — derived judgment or unresolved work. Used by decisions and open items.

A fact, retrieved document fragment, summary, tool result, or decision may contain imperative language. That does not grant it control authority.

## Trust level

Each item also carries a `trust_level`:

- `trusted` — explicitly authoritative for its declared role.
- `reviewed` — inspected or promoted into governed state by a trusted actor/process.
- `untrusted` — may be useful as evidence but must not execute as control.

Active instructions must be `trusted` or `reviewed`. The compiler fails closed if an applicable active instruction is marked `untrusted` or lacks valid control authority.

## Origin

`origin.kind` records provenance such as `user`, `system`, `agent`, `tool`, `file`, `web`, or `import`.

Origin is not authority. A web page can be useful evidence without being allowed to instruct the agent. An imported file that contains "ignore previous instructions" remains data until a trusted actor explicitly promotes a specific rule into the governed instruction registry.

## Compiler planes

The Context Compiler emits two explicit sections:

1. `CONTROL PLANE` — only active, in-scope, authorized governed instructions.
2. `DATA PLANE` — facts, assumptions, decisions, open items, and other evidence/advisory state.

The data-plane header states that imperative text inside data is quoted content and must not be promoted to control.

## Fail-closed rules

The compiler rejects or blocks:

- untrusted active control instructions;
- instructions whose `authority` is not `control`;
- task exclusions that try to suppress applicable active control instructions;
- required instructions outside the task scope;
- semantic retrieval candidates that reference stale, unknown, excluded, out-of-scope, or unauthorized instruction state.

## What this does not solve

This boundary cannot inspect opaque platform system prompts, model weights, or hidden host context. It protects the state and context surfaces that the agent or host explicitly manages.
