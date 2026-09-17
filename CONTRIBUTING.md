# Contributing

Contributions should preserve the project's main property: explicit, auditable state transitions are preferred over hidden heuristics.

## Development

Runtime scripts use only the Python standard library. Development checks additionally use `jsonschema` to validate the published schemas and examples.

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python scripts/release_audit.py --full
```

## Change requirements

For behavior changes:

1. Add or update tests.
2. Update the relevant schema when the machine-readable contract changes.
3. Update `SKILL.md` and reference documentation when agent behavior changes.
4. Preserve fail-closed behavior at the control/data boundary.
5. Add a changelog entry.

Do not add a third-party runtime dependency without a strong reason and an explicit design discussion.

## Security-sensitive changes

Changes to trust, authority, instruction scope, context compilation, state parsing, checkpoint integrity, or provenance are security-sensitive. Include adversarial tests and explain the invariant being preserved.
