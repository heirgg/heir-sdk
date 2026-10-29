# Releasing

Each package is released on its own, by a tag named after it. Pushing the tag runs that package's checks once more and
publishes it; nothing is published from a plain commit to `main`.

| Package | Tag | Goes to |
| --- | --- | --- |
| `typescript/` | `typescript/vX.Y.Z` | npm as `@heir/sdk`, with provenance |
| `python/` | `python/vX.Y.Z` | PyPI as `heir-sdk`, by trusted publishing |
| `go/` | `go/vX.Y.Z` | the Go module proxy, which reads the tag itself |

The `go/` prefix is what Go requires for a module that lives in a subdirectory, so the other two follow the same shape.

## Cutting a release

1. Bump the version in the package's manifest and its version constant, which a test keeps in step:
   - TypeScript: `typescript/package.json` and `typescript/src/version.ts`
   - Python: `python/pyproject.toml` and `python/src/heir/_version.py`
   - Go: `go/version.go` (the tag is the manifest)
2. Commit to `main` and wait for CI.
3. Tag the commit and push the tag:

   ```bash
   git tag typescript/v0.1.0 && git push origin typescript/v0.1.0
   ```

   The release workflow refuses a tag whose version does not match the manifest, so a stray tag publishes nothing.
4. The workflow publishes and creates a GitHub release with generated notes.

Versions follow semver per package. The three packages share one API but need not share version numbers.

## One-time setup

- **npm**: the `@heir` scope must exist on npmjs.com and be owned by the publishing account or organization. Create a
  granular access token with publish rights for the scope, and store it as the `NPM_TOKEN` secret of a GitHub
  environment named `npm`. Once the package has been published a first time, it can be switched to npm trusted
  publishing (no token) from the package's settings page, and the token removed.
- **PyPI**: add a *pending publisher* on pypi.org for project `heir-sdk` with owner `heirgg`, repository `heir-sdk`,
  workflow `release-python.yml` and environment `pypi`, then create a GitHub environment named `pypi`. The first
  release creates the project. No token is stored anywhere.
- **Go**: nothing. The module path is fixed by the repository; the repository being public is all the proxy needs.

## After a spec change

Refresh `spec/` from the backend (`npm run openapi:build` there, then copy `docs/public-api/*.json` in), regenerate
each package (`npm run generate`, `go generate ./...`, `python scripts/generate.py`), and release whichever packages
changed. CI fails when generated code is out of date with `spec/`.
