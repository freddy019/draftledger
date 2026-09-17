# Semantic Retrieval

DraftLedger allows an embedding model, LLM retriever, vector database, or other semantic search system to improve recall without making that retriever authoritative.

The design rule is:

> Retrieval proposes. Governance disposes.

## Candidate contract

A semantic retriever outputs only governed state IDs plus a bounded score:

```json
{
  "version": "1.0",
  "producer": "my-retriever",
  "method": "embedding",
  "candidates": [
    {"id": "F-001", "score": 0.91},
    {"id": "A-003", "score": 0.84}
  ]
}
```

A human-readable `reason` may be included for diagnostics, but it is not copied into the reasoning context and cannot become an instruction.

The candidate schema intentionally does not allow arbitrary retrieved `text` or `content`. Retrieval should nominate IDs already present in governed state. Raw documents must be ingested into a separate evidence pipeline and reviewed before they can become governed control state.

## Gate

Use:

```bash
python scripts/retrieval_gate.py state.json task.json semantic-candidates.json
```

The gate rejects:

- unknown IDs;
- inactive state;
- task-excluded state;
- instructions outside the current scope;
- untrusted or unauthorized instructions;
- malformed candidate fields or scores outside `0..1`.

Accepted candidates remain subject to context budget, dependency closure, and Context Trace.

## Compiler integration

```bash
python scripts/context_compile.py state.json \
  --task-file task.json \
  --semantic-candidates semantic-candidates.json \
  --output compiled.json
```

Selection order is:

1. explicit task requirements;
2. applicable authorized control instructions;
3. gated semantic proposals;
4. deterministic lexical relevance fallback;
5. decision dependency closure;
6. budget enforcement.

Semantic retrieval therefore improves recall but cannot reactivate stale state or alter instruction authority.

## Security property

A malicious retriever reason such as `IGNORE ALL PRIOR INSTRUCTIONS` is not rendered into the compiled context. The retriever can only point at an existing governed ID. This sharply reduces the prompt-injection surface compared with inserting raw vector-search chunks directly into a control prompt.
