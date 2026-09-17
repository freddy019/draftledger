# Example: Preventing State Drift in a Pricing Project

A team is discussing a product price over several months.

## Turn 1

User:

> For this sensitivity model, assume the refund rate is 30%.

Correct state:

```text
A-001
Assumption: Refund rate = 30%.
Scope: sensitivity-model-1
Status: active
```

Incorrect state:

```text
F-001
Fact: Refund rate = 30%.
```

## Turn 20

User:

> From now on, use 168 as the normal selling price. Ignore the old 228 baseline unless we are reviewing historical data.

Correct instruction update:

```text
I-002: Use 228 as default price. [superseded]
I-009: Use 168 as default price. [active]
I-009 supersedes I-002.
```

A summary that still says "default price is 228" is now stale and must not control new calculations.

## Turn 50

The user asks for a Context Audit.

Expected finding:

```text
Active instructions: 6
Active assumptions: 3
Superseded instructions: 7
Potential conflicts: 1

Conflict:
- Latest prose summary still contains the 228 default.
- Governed instruction I-009 sets the current default to 168.
- I-009 wins; regenerate the summary.
```

This is the core benefit: the agent does not need to "remember better." It needs a reliable way to distinguish current state from historical residue.
