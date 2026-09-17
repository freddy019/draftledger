# Publishing DraftLedger

The public repository name is `draftledger`. The first public tag is `v0.1.0-alpha.1`.

## Release gate

1. Run `python scripts/release_audit.py --full --strict` from the repository root.
2. Build `draftledger-v0.1.0-alpha.1.zip` with `python scripts/build_release.py`.
3. Extract the ZIP into a clean directory and repeat the strict audit there.
4. Rebuild from the extracted tree and confirm the archive SHA-256 is identical.
5. Push the audited commit to GitHub and wait for the required GitHub Actions matrix to pass.
6. Create and push the annotated tag `v0.1.0-alpha.1` on that exact commit.
7. Create a GitHub prerelease using `RELEASE_NOTES.md` as the release body. Attach the ZIP and `.zip.sha256` sidecar.
8. Download the published assets and verify the sidecar before announcing the release.

Do not describe the alpha as stable. The release title and repository description should identify it as an experimental preview.
