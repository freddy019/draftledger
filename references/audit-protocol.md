# Context Audit Protocol

Use Context Audit to expose the state currently shaping the agent's reasoning.

## Procedure

### 1. Enumerate active state

Report:

- active facts relevant to the current task;
- active assumptions;
- active instructions;
- active decisions;
- open items.

### 2. Inspect stale state

Find:

- superseded instructions still present in summaries;
- assumptions with no validation path;
- old facts that may no longer be current;
- decisions whose supporting assumptions changed;
- project-level instructions that may really be task-scoped.

### 3. Detect conflicts

Classify each conflict:

- fact vs fact;
- fact vs assumption;
- instruction vs instruction;
- decision vs new evidence;
- summary vs governed state.

### 4. Produce an audit report

Recommended format:

```text
Context Audit

Active instructions: 8
Active assumptions: 5
Unverified assumptions: 2
Superseded instructions: 11
Active decisions: 4
Open items: 3
Potential conflicts: 1

Material findings:
- I-004 is superseded by I-011 but still appears in the latest summary.
- D-004 depends on A-003, which has not been validated.
```

### 5. Resolve only with authority

Do not silently delete ambiguity. If the correct state cannot be inferred safely, ask for a decision or label the state unresolved.

## Audit frequency

Do not run a full audit on every turn. Good triggers include:

- phase transition;
- major requirement change;
- handoff;
- unexpected output drift;
- repeated correction by the user;
- suspected prompt contamination.
