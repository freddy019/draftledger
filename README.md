# Agent State Governance

**Don't just remember context. Govern state.**

Agent State Governance is a portable Agent Skill for long-running AI work. It adds a small control layer between raw conversation history and model reasoning so that facts, assumptions, instructions, decisions, and compressed summaries do not silently collapse into one another.

**Release status:** `1.0.0`. Runtime: Python 3.11+ standard library only. The public machine-readable protocol is frozen at `1.0` for the stable 1.x line.

## The problem

Long-running AI tasks often fail for reasons that are not primarily about model intelligence:

- context compression is lossy;
- temporary assumptions become "facts" after repeated summarization;
- old instructions remain active after their intended scope has ended;
- newer instructions conflict with older ones;
- decisions survive while the rationale behind them disappears;
- handoffs preserve prose summaries but lose task state;
- users cannot see which old prompt is still influencing the answer.

The result is **state drift**: the model continues reasoning coherently from an increasingly incorrect representation of the project.

This skill treats that as a governance problem rather than a memory problem.

## Core model

```text
Raw history / source artifacts
            │
            ▼
┌──────────────────────────────┐
│   Governed State Layer       │
│                              │
│  Facts                       │
│  Assumptions                 │
│  Instructions                │
│  Decisions                   │
│  Open Items                  │
└──────────────────────────────┘
            │
            ▼
   Current reasoning context
            │
            ▼
      Derived summaries
```

A summary is a cache. It is not the database.

## What makes this different

This project is adjacent to context engineering, memory systems, and decision logging, but focuses on a narrower control-plane problem: **lifecycle management of task state**.

The key distinction is that each important item has a type and lifecycle:

- a fact can be active, disputed, or superseded;
- an assumption can be active, confirmed, rejected, or expired;
- an instruction can be active, superseded, expired, or revoked;
- a decision can be active, superseded, or reversed.

This prevents a common failure mode where repeated compression gradually erases epistemic status.

## Context Compiler

The Context Compiler prevents contamination before reasoning begins. Instead of passing the whole project history, it selects a bounded set of active state for one task.

```bash
python scripts/context_compile.py examples/sample-state.json \
  --task-file examples/compiler-task.json \
  --context-output /tmp/context.txt \
  --manifest-output /tmp/context-manifest.json

python scripts/context_trace.py lint examples/sample-state.json /tmp/context-manifest.json --strict
```

The deterministic baseline uses explicit requirements, scope-aware active instructions, lexical relevance, and Decision dependency closure. It fails closed rather than silently dropping required control state when the context budget is too small.

Read `references/context-compiler.md` for the selection policy and extension points.

## Semantic Retrieval and Trust Boundary

v0.8 allows semantic search to improve recall without turning the retriever into an authority. A retriever may only nominate existing governed state IDs with bounded scores. The compiler then re-checks lifecycle, task scope, exclusions, authority, and trust before an item can enter context.

```bash
python scripts/retrieval_gate.py \
  examples/sample-state.json \
  examples/compiler-task.json \
  examples/semantic-candidates.json

python scripts/context_compile.py examples/sample-state.json \
  --task-file examples/compiler-task.json \
  --semantic-candidates examples/semantic-candidates.json \
  --output /tmp/compiled-context.json
```

Compiled context is split into an explicit `CONTROL PLANE` and `DATA PLANE`. Facts, assumptions, decisions, tool/file/web-derived material, and retriever text cannot become executable instructions merely because they appear in context. Active control instructions must be in-scope and marked `trusted` or `reviewed`.

**Data must never become instruction merely because it entered context.**

Read `references/semantic-retrieval.md` and `references/trust-boundary.md`.

## Hardening

v0.9 hardens the state/control boundary rather than adding another large feature. All CLI JSON readers now use strict parsing with duplicate-key rejection, non-finite-number rejection, UTF-8 validation, and bounded file/depth/node/string limits. State writes are atomic and fsync-backed. State VCS mutations use a process-level advisory repository lock, and Context Trace now rejects cyclic summary provenance.

A release-oriented check composes state linting, trust-boundary checks, and optional declared-context provenance:

```bash
python scripts/hardening_check.py examples/sample-state.json --strict
```

The test suite also includes deterministic fuzzing, checkpoint-tamper detection, concurrent VCS mutation, symlink-safe atomic replacement, and a multilingual prompt-injection regression corpus.

Read `references/hardening.md` for the threat model and release checklist. Passing the hardening suite reduces known failure modes; it is not a claim that the software is vulnerability-free.

## Context Audit

The skill defines a small state-control stack: semantic `Context Audit`, deterministic `Context Lint`, `State Diff`, explicit `Revalidation Workflow`, append-only `State Version Control`, declared `Context Provenance`, and a task-scoped `Context Compiler`. An audit surfaces the hidden state currently shaping the model's behavior:

```text
Active instructions: 8
Active assumptions: 5
Unverified assumptions: 2
Superseded instructions: 11
Active decisions: 4
Open items: 3
Potential conflicts: 1
```

The user can then revoke, rescope, confirm, or supersede specific items instead of trying to "fix the prompt" blindly.

## Release validation

Before a stable release, run the complete audit:

```bash
python -m pip install -r requirements-dev.txt
python scripts/release_audit.py --full --strict
```

The runtime tooling remains dependency-free; `jsonschema` is a development-only validator used to verify the published schemas and examples. `scripts/build_release.py` runs the full audit, creates a deterministic ZIP, excludes caches/local state, and writes a SHA-256 sidecar. See `references/release-audit.md` and `SECURITY.md`.

## Repository layout

```text
agent-state-governance/
├── SKILL.md
├── agents/openai.yaml
├── README.md
├── README.zh-CN.md
├── CHANGELOG.md
├── SECURITY.md
├── CONTRIBUTING.md
├── VERSION
├── LICENSE
├── requirements-dev.txt
├── .github/workflows/ci.yml
├── references/
│   ├── state-model.md
│   ├── instruction-lifecycle.md
│   ├── compression-policy.md
│   ├── audit-protocol.md
│   ├── context-lint.md
│   ├── state-diff.md
│   ├── revalidation-workflow.md
│   ├── version-control.md
│   ├── context-provenance.md
│   ├── context-compiler.md
│   ├── semantic-retrieval.md
│   ├── trust-boundary.md
│   ├── hardening.md
│   └── release-audit.md
├── templates/
│   ├── STATE.md
│   ├── INSTRUCTIONS.md
│   ├── ASSUMPTIONS.md
│   ├── DECISIONS.md
│   ├── AUDIT.md
│   └── state.json
├── schemas/
│   ├── state.schema.json
│   ├── revalidation-plan.schema.json
│   ├── revalidation-resolution.schema.json
│   ├── context-manifest.schema.json
│   ├── compiled-context.schema.json
│   ├── semantic-candidates.schema.json
│   └── retrieval-gate-report.schema.json
├── scripts/
│   ├── context_lint.py
│   ├── state_diff.py
│   ├── revalidate.py
│   ├── state_vcs.py
│   ├── context_trace.py
│   ├── context_compile.py
│   ├── retrieval_gate.py
│   ├── safe_io.py
│   ├── hardening_check.py
│   ├── release_audit.py
│   └── build_release.py
├── tests/
│   ├── test_context_lint.py
│   ├── test_state_diff.py
│   ├── test_revalidate.py
│   ├── test_state_vcs.py
│   ├── test_context_trace.py
│   ├── test_context_compile.py
│   ├── test_safe_io.py
│   └── test_hardening.py
├── security/
│   ├── README.md
│   └── prompt-injection-corpus.json
└── examples/
    ├── pricing-project.md
    ├── sample-state.json
    ├── broken-state.json
    ├── diff-before.json
    ├── diff-after.json
    ├── review-state.json
    ├── revalidation-plan.json
    ├── revalidation-resolution.json
    ├── revalidated-state.json
    ├── context-manifest-clean.json
    ├── context-manifest-contaminated.json
    ├── compiler-task.json
    └── semantic-candidates.json
```


## Context Lint

`Context Audit` is semantic and agent-driven. `Context Lint` is deterministic and machine-checkable.

The v0.2 linter validates state invariants that are easy to lose during long-running work:

- dangling IDs and broken decision dependencies;
- rejected/expired assumptions still supporting active decisions;
- superseded facts still supporting active decisions;
- instruction supersession cycles;
- multiple active instructions for the same `key + scope + scope_id`;
- confirmed assumptions that were never promoted to facts.

Run it with no third-party dependencies:

```bash
python scripts/context_lint.py .agent-state/state.json
python scripts/context_lint.py .agent-state/state.json --strict
python scripts/context_lint.py .agent-state/state.json --json
```

The optional `key` field gives mutable instructions a stable identity such as `default-price`, `output-format`, or `approval-policy`. This makes some forms of prompt contamination mechanically detectable rather than dependent on the model noticing them.


## State Diff and dependency revalidation

A state snapshot tells you what is true now; it does not tell you which old conclusions became unsafe when that state changed. `State Diff` compares two snapshots, traces changed facts/assumptions/instructions into decision dependencies, and identifies decisions that must be revalidated.

```bash
python scripts/state_diff.py before.json after.json
python scripts/state_diff.py before.json after.json --fail-on-review
python scripts/state_diff.py before.json after.json --write-review-state state.review.json
```

The important rule is simple: **changing a premise is allowed; silently continuing to trust conclusions derived from that premise is not.**


## Explicit revalidation workflow

`State Diff` can identify which decisions became unsafe. v0.4 adds the next step: an explicit lifecycle for resolving them without pretending that dependency substitution is equivalent to reasoning.

```bash
python scripts/state_diff.py before.json after.json \
  --write-review-state state.review.json

python scripts/revalidate.py plan state.review.json \
  --output revalidation-plan.json

python scripts/revalidate.py apply state.review.json resolution.json \
  --output state.revalidated.json

python scripts/context_lint.py state.revalidated.json --strict
```

The planner can follow deterministic lineage such as a superseded fact or instruction and expose candidate replacements. It deliberately does **not** auto-reactivate a decision. The semantic review must select one of four outcomes: `revalidated`, `superseded`, `reversed`, or `blocked`.

This creates a clean separation of responsibilities: the machine handles graph integrity and lifecycle transitions; the agent or human handles judgment.

## State checkpoints, branches, rollback, and merge

v0.5 adds an append-only version-control layer for governed state. This is useful when an agent needs to explore alternative scenarios without contaminating the main task state.

```bash
python scripts/state_vcs.py init .agent-state/state.json
python scripts/state_vcs.py branch scenario-b
python scripts/state_vcs.py switch scenario-b --output .agent-state/state.json
python scripts/state_vcs.py checkpoint .agent-state/state.json -m "scenario B assumptions"
python scripts/state_vcs.py diff main scenario-b
python scripts/state_vcs.py switch main --output .agent-state/state.json
python scripts/state_vcs.py merge scenario-b --output .agent-state/state.json
```

Checkpoints are immutable. Rollback creates a new checkpoint instead of deleting newer history. Merge uses a three-way, ID-aware merge and reports same-field conflicts explicitly. After a clean merge, changed premises are traced into Decision dependencies and affected Decisions are automatically marked `needs_review`.

This gives long-running agents a lightweight equivalent of semantic version control:

```text
checkpoint -> branch -> diff -> merge -> revalidate
                 \-> rollback
```

The important rule remains: **a clean merge is not proof that an old conclusion is still valid.**

## Context provenance and contamination detection

v0.6 separates **valid state** from **context actually fed into reasoning**. A project can have a perfectly clean state registry while an old summary, handoff, memory fragment, or superseded instruction is still present in the assembled context.

`context_trace.py` records a declared Context Manifest and checks it against current governed state:

```bash
python scripts/context_trace.py build .agent-state/state.json \
  --ids F-001 A-001 I-009 D-001 \
  --output .agent-state/context-manifest.json

python scripts/context_trace.py lint \
  .agent-state/state.json \
  .agent-state/context-manifest.json --strict

python scripts/context_trace.py explain \
  .agent-state/state.json \
  .agent-state/context-manifest.json
```

It detects stale state entries, superseded instructions that still shadow active instructions, in-place snapshot changes, tainted summaries, summary-of-summary taint propagation, and unmanaged context.

The boundary is deliberate: this tool audits **declared controllable context**. It does not claim to introspect hidden platform prompts or model internals.

The core distinction is:

- `Context Lint`: is the governed state internally valid?
- `Context Trace`: is the reasoning context actually drawn from valid state?

A clean database does not guarantee a clean answer if the application is still serving an old cache.

## Installation

Agent Skills are directory-based. Copy this repository, or the skill folder, into the skills directory used by your host.

Common project-scoped locations include:

```text
.agents/skills/agent-state-governance/
.claude/skills/agent-state-governance/
.cursor/skills/agent-state-governance/
.codex/skills/agent-state-governance/
```

The required entry point is `SKILL.md`.

## Quick start

1. Install the skill.
2. Ask the agent to initialize governed state for a long-running task.
3. Keep raw source material separate from `.agent-state/`.
4. Ask for a **context audit** when a project changes phase or the output starts to feel "mysteriously biased" by old context.

Suggested prompt:

```text
Initialize Agent State Governance for this project. Separate confirmed facts,
working assumptions, active instructions, decisions, and open items. Do not
promote assumptions during summarization. Run a context audit before major
phase changes.
```

## Design principles

- **Epistemic separation** — facts and assumptions are different data types.
- **Instruction lifecycle** — instructions have scope, priority, and expiry.
- **Decision provenance** — conclusions retain rationale and dependencies.
- **Loss-aware compression** — summaries cannot silently redefine state.
- **Incremental mutation** — update deltas instead of rewriting everything.
- **Auditability** — hidden prompt residue should be inspectable.
- **Reversibility** — superseded state keeps enough lineage to reconstruct why it changed.

## Related work

This skill is intentionally complementary to broader context-engineering and memory projects, including:

- Agent Skills for Context Engineering — https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering
- ai-agent-skills — https://github.com/shenwell/ai-agent-skills
- Agent Skills / skill creator references — https://github.com/openai/skills

Those projects cover broader context management, memory, evaluation, or agent architecture. Agent State Governance focuses specifically on the control plane between history and reasoning.

## Status

`v1.0.0 Final` — stable source release. The public state/context protocol remains `1.0`; runtime tools require only the Python standard library. See [final audit](FINAL_AUDIT.md), [release notes](RELEASE_NOTES.md), and [publication procedure](PUBLISHING.md) for verification evidence and the remaining GitHub CI gate.

## License

MIT
