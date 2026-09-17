# State Model

This reference defines the logical data model used by DraftLedger.

## Why typed state matters

Long-running tasks fail when different epistemic objects are flattened into prose. The most dangerous flattening is assumption -> fact, but the same problem occurs with active -> expired instructions and decision -> immutable truth.

Treat each item as a typed state object.

## Fact

Recommended fields:

```text
id: F-001
statement: The current unit price is 168.
source: user-confirmed
scope: project
status: active
last_confirmed: 2026-09-16
```

Use `disputed` when credible sources conflict. Use `superseded` when the fact was historically correct but is no longer current.

## Assumption

```text
id: A-003
statement: Refund rate is assumed to be 30% for this scenario.
confidence: medium
scope: scenario-2
reason: User requested provisional modeling.
validation_condition: Replace when observed refund data is available.
status: active
```

Assumptions must never lose their provisional marker during compression.

## Instruction

```text
id: I-007
instruction: Use 168 as the default price unless an activity price is explicitly provided.
scope: project
priority: normal
status: active
supersedes: I-002
expiry_condition: User provides a new default price.
```

## Decision

```text
id: D-004
decision: Keep the current price for the next test cycle.
rationale: Conversion weakness appears linked to trust signals rather than price alone.
facts_used: [F-001, F-009]
assumptions_used: [A-003]
status: active
```

If A-003 is rejected later, D-004 should be flagged for review.

## Open item

```text
id: O-002
type: pending-verification
statement: Verify whether the new fulfillment fee applies to all channels.
status: open
owner: agent
```

## State dependency

A useful mental model is a directed graph:

```text
Facts ───────┐
             ├──> Decisions ───> Plans / Outputs
Assumptions ─┘

Instructions ────────────────> How reasoning and execution are performed
```

When a fact or assumption changes, inspect downstream decisions before continuing.
