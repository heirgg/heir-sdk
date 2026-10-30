# Release an SDK package

Release each language independently from a reviewed commit on `main`. Publishing starts when a release owner pushes its package tag; ordinary commits do not publish packages. Do not push a tag until local preflight, CI, source provenance, and account setup are ready.

| Package | Tag | Destination |
| --- | --- | --- |
| TypeScript | `typescript/vX.Y.Z` | npm `@heirgg/sdk` |
| Python | `python/vX.Y.Z` | PyPI `heir-sdk` |
| Go | `go/vX.Y.Z` | `github.com/heirgg/heir-sdk/go` |

The current `spec/source.json` has `uncommittedSource: true`. Replace it using the sync script against committed backend documents before releasing. Changing the flag manually would discard the provenance guarantee. A committed snapshot still needs confirmation against the backend version you intend to support.

## Complete account and repository setup

These are release-owner actions. The workflows cannot establish ownership, make the repository public, or configure trust on your behalf:

- Make the source publicly accessible before the open source launch and public Go module resolution.
- Protect `main`, require CI/review, and restrict creation or movement of package release tags. Configure the `npm` and `pypi` GitHub environments with appropriate reviewers and deployment/tag restrictions.
- Enable GitHub private vulnerability reporting as described in [SECURITY.md](SECURITY.md).
- Verify ownership of npm scope `@heirgg` and package `@heirgg/sdk`.
- Configure npm Trusted Publishing using the settings below. The workflow authenticates through GitHub's OpenID Connect (OIDC) identity and has no publish-token secret or token fallback. It uses Node 24, verifies npm 11.5.1+, and grants `id-token: write` only to the publishing job. See [npm trusted publishers](https://docs.npmjs.com/trusted-publishers/).
- Configure a PyPI pending publisher for `heir-sdk`, owner `heirgg`, repository `heir-sdk`, workflow `release-python.yml`, and environment `pypi`. The Python workflow uses trusted publishing without a registry token. See [PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/).

Go needs no registry credential. **A public `go/v…` tag can be discovered before its workflow runs.** Workflow failure cannot prevent publication through the Go module protocol. Validate before creating or pushing the tag.

### npm Trusted Publisher settings

In `@heirgg/sdk` package settings on npm, add a GitHub Actions trusted publisher:

| Field | Value |
| --- | --- |
| Organization or user | `heirgg` |
| Repository | `heir-sdk` |
| Workflow filename | `release-typescript.yml` |
| Environment | `npm` |
| Allowed actions | Enable **Allow npm publish** |

Enter the workflow filename without `.github/workflows/`. New configurations default to staged publishing, so direct `npm publish` must be explicitly allowed. The workflow already uses GitHub-hosted runners. Make the repository public before using its configured provenance publication.

[npm requires the package to exist before trust can be configured](https://docs.npmjs.com/cli/v11/commands/npm-trust/). Creating the trust configuration alone does not publish anything. This is separate from PyPI's pending-publisher flow.

### Create the npm package before its first automated release

To establish `@heirgg/sdk` before releasing SDK contents, use [npm staged publishing](https://docs.npmjs.com/staged-publishing/) with an owner account that can publish under `@heirgg` and has 2FA enabled. This needs npm 11.15.0+ and Node 22.14.0+. It creates a **public `0.0.0-stage` placeholder** and uploads the SDK to npm's staging area; the SDK version and its contents remain unpublished until approved.

From this repository, run these owner-authenticated commands when ready to make the package name public:

```bash
cd typescript
npm login --auth-type=web --registry=https://registry.npmjs.org
npm run generate:check
npm run typecheck
npm test
npm run test:package
npm stage publish --registry=https://registry.npmjs.org --access=public --provenance=false
```

The final command changes registry state. Save the stage ID it returns. `--provenance=false` overrides the package's CI provenance setting for this local operation; it does not change the manifest or the automated release workflow.

Configure the trusted publisher using the settings above, or through the authenticated CLI:

```bash
npm trust github @heirgg/sdk --repo=heirgg/heir-sdk --file=release-typescript.yml --env=npm --allow-publish
```

Then reject the staged SDK upload using its returned ID:

```bash
npm stage reject <stage-id>
```

Rejecting the staged upload removes the pending SDK version so the direct-publish workflow can publish that version later; the public placeholder has established the package. Do not approve this setup upload: approval releases its contents, and an existing staged version blocks direct publication of the same version. See [npm stage version behavior](https://docs.npmjs.com/cli/v11/commands/npm-stage/).

The first real SDK release still follows the committed-spec, review, CI, and preflight requirements below. Keep CI authenticated solely through OIDC; no publishing token is needed in GitHub secrets. Create the trust configuration close to the intended release: npm requires its first successful trusted publish within two days, otherwise it must be recreated.

## Prepare the release commit

Finish the source and version updates before tagging:

1. Regenerate backend documents, commit them in the intended backend revision, and run `python3 scripts/sync-spec.py /path/to/backend/docs/public-api` from this repository.
2. Regenerate affected SDKs and update shared fixtures. Run the checks in [CONTRIBUTING.md](CONTRIBUTING.md).
3. Update `CHANGELOG.md` and the package's version sources. TypeScript uses `package.json`, its lockfile, and `src/version.ts`; Python uses `pyproject.toml` and `src/heir/_version.py`; Go uses `version.go`.
4. Merge the reviewed change to `main`, fetch `origin`, and check out the exact `origin/main` commit. Confirm that commit's required CI checks passed.

Run the read-only preflight with the intended package and tag, for example:

```bash
python3 scripts/release.py typescript typescript/v0.1.0 --preflight
```

Preflight checks version agreement, a clean checkout, `main` matching local `origin/main`, snapshot hashes, shared fixture coverage, and committed spec provenance. It does not fetch Git refs, check hosted CI, verify registry permissions, or create/push a tag. Fetch and verify those separately.

After preflight succeeds and the release owner approves publishing, create and push the intended tag:

```bash
git tag typescript/v0.1.0
git push origin typescript/v0.1.0
```

Substitute the selected package/version in both commands. Go major versions 2+ require a module-path migration before release; preflight rejects them with the current module path.

## Understand the publishing jobs

The build/verify job runs with read-only repository permissions. It fetches complete history, verifies the tag matches the checked-out commit and belongs to `origin/main`, validates version/provenance, tests the client, and builds artifacts. A separate environment-protected job downloads the validated artifact and publishes it with only the permissions it needs. A final job creates GitHub release notes with repository write permission. Configure the remote tag rules and approvals described in [contributor security](docs/contributor-security.md); the ancestry check alone cannot restrict a person who can create arbitrary tags and alter workflow code.

TypeScript publishes the tarball without lifecycle scripts. Python publishes the built wheel and source archive. Artifact IDs bind publication to that workflow run. External Actions use immutable commits; Dependabot proposes updates.

Go validates and asks the public proxy to resolve its tag, then creates release notes. This check confirms discoverability after the tag already exists.

## Choose a prerelease channel

TypeScript and Go tags accept versions such as `0.2.0-rc.1`; Python uses its native forms such as `0.2.0rc1` or `0.2.0.dev1`. Set the same version in the package's version sources. Build metadata is not supported by the release helper.

TypeScript prereleases publish with npm dist-tag `next`; stable releases use `latest`. Python versions follow PyPI prerelease handling. GitHub release notes mark prereleases and do not select a monorepo-wide latest release automatically.

## Recover from a partial release

Rerun the failed jobs from the same workflow run when publication succeeded but release-note creation failed. Publishing checks compare local artifacts with registry hashes. Exact matches skip publication; a mismatch stops the workflow instead of accepting different bytes under one version. Python can finish uploading missing distributions when existing files match.

Keep the original validated artifacts for recovery. If a rerun rebuilds different bytes, investigate the dependency/build difference; do not bypass the digest check. Never move a published tag or try to overwrite a published version. Correct a released defect with a new package version.

After success, install the released package in a clean consumer and verify its reported version. Record the release URL and any backend compatibility notes in the changelog.
