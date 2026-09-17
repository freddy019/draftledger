# Release Audit

The release audit verifies that the repository can be consumed both as an Agent Skill and as a small deterministic state-governance toolkit.

Run:

```bash
python scripts/release_audit.py --full --strict
```

The audit checks:

- Agent Skills frontmatter constraints and directory-name consistency;
- OpenAI `agents/openai.yaml` interface metadata;
- JSON syntax, protocol versions, and JSON Schema validity when `jsonschema` is installed;
- static example/schema compatibility;
- Python compilation and CLI `--help` behavior;
- hardening, context compilation, provenance, revalidation, State VCS, retrieval-gate, and multi-agent handoff smoke flows;
- the full unit test suite with `--full`;
- release-tree hygiene warnings for caches and local state.

`python scripts/build_release.py` runs the full audit by default, then creates a deterministic ZIP and SHA-256 sidecar while excluding local caches, `.git`, and `.agent-state` data.

Passing the audit means the known contracts and regressions passed. It is not proof that the project has no defects or vulnerabilities.
