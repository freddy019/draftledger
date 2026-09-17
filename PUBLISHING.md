# GitHub publication preparation

The v1.0.0 source and release assets are prepared locally. No remote repository, push, tag publication, or GitHub Release has been created by this audit.

The local preparation commit uses `Release preparation <release-preparation@localhost>` to identify the automated preparation rather than invent a personal author identity. Set your own Git identity for subsequent maintainer commits.

1. Choose the GitHub owner, repository visibility, and confirm the copyright holder for the existing MIT license. The supplied license only identifies the year; this audit does not infer legal ownership.
2. Review the source, `FINAL_AUDIT.md`, and `RELEASE_NOTES.md`. Use repository name `agent-state-governance` (the skill directory name is part of the audit contract).
3. Create an empty GitHub repository, then configure its remote and push the reviewed main branch. Do not include private governed state, environment files, or audit environments.
4. Wait for all six CI matrix jobs (Linux, Windows, macOS; Python 3.11 and 3.13). Local Windows checks do not establish a green hosted matrix. Resolve any failure before publishing the release tag.
5. Enable private vulnerability reporting and branch protection as appropriate for the selected account. Verify the security reporting route before announcing public availability.
6. After CI passes, create the annotated `v1.0.0` tag on the audited commit, push the tag, and create a GitHub Release with `RELEASE_NOTES.md` as the body. Attach `agent-state-governance-v1.0.0.zip` and its `.zip.sha256` sidecar. Verify downloaded asset hashes before announcement.

## Local verification commands

Run from the repository root using Python 3.11+:

```sh
python -m pip install -r requirements-dev.txt
python -B scripts/release_audit.py --full --strict
python -B scripts/build_release.py
```

The archive is written to the parent directory. Keep build output outside the repository. ZIP contents use a fixed timestamp, POSIX mode metadata and sorted file order; repeatability is checked for the same source bytes and Python/zlib environment. Cross-version compressor output is not promised byte-identical.

Examples elsewhere use Bash multiline syntax and `/tmp`; Windows PowerShell users can run a single line and choose a writable local output path. Runtime tools can be used directly after extraction without pip installation; only release schema validation needs the development dependencies.
