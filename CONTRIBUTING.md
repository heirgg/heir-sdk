# Contribute to the Heir SDKs

Use this guide to set up a checkout, change a client, and run its checks. Keep changes scoped to the affected languages and include a reproduction for behavior changes.

Maintainers configure [contributor and release protections](docs/contributor-security.md). External contributions use fork pull requests and do not require repository write access.

See [dependency maintenance](docs/dependency-updates.md) for the current toolchains and the upstream compatibility limits that require coordinated updates.

## Set up your checkout

Clone the repository or your fork. You need Python 3.10+ for root tooling, current Node 24 or 26 for TypeScript development, and Go 1.23+ for the Go runtime. The published JavaScript SDK still supports Node 20; its build and test tools need a newer Node version. Go's generator may require a newer toolchain; use current stable Go when regenerating models.

From the repository root, verify the contract snapshot and shared fixtures:

```bash
python3 scripts/sync-spec.py --check
python3 scripts/check-contracts.py
python3 -m unittest discover -s tests -v
```

The fixture check verifies operation coverage and routes. Language tests check encoding and decoding through public client methods. These checks do not establish deployment parity.

## Work on TypeScript

Run these commands from `typescript/`:

```bash
npm ci
npm --prefix tools/codegen ci
npm run generate:check
npm run typecheck
npm test
npm run test:package
```

`test:package` builds and installs the actual tarball into a temporary consumer. It compiles ESM/CommonJS imports with both the compatibility and native TypeScript compilers, runs them, checks retry behavior in a child process, and runs offline examples. After building with current Node, `npm run test:runtime` runs only installed-package and example checks on Node 20. Add tests for request lifetime, cancellation, body-stream failures, or declaration exports when touching those paths.

## Work on Python

Create an environment and run these commands from `python/`:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]' -c requirements-dev.txt
python scripts/generate.py --check
ruff check .
ruff format --check .
mypy
pytest
python -m build --no-isolation
python scripts/check_wheel.py
```

Exercise sync and async behavior together. Preserve omitted versus explicit-null fields, including mutations of nested defaults. The test suite covers asyncio and Trio.

`requirements-dev.txt` pins the newest tested toolchain with Python-version markers. On Python 3.11+, audit it with `pip-audit -r requirements-dev.txt --no-deps --disable-pip --strict --progress-spinner off`. The Python README documents how to refresh the universal constraints; keep the public SDK's runtime ranges compatible rather than pinning every consumer to the development environment.

## Work on Go

Run these commands from `go/` with current stable Go:

```bash
gofmt -w .
go run -C internal/gen . -check
go vet ./...
go test -race -shuffle=on -count=1 ./...
```

CI also runs the pinned golangci-lint and govulncheck versions in [.github/workflows/ci.yml](.github/workflows/ci.yml). Keep the published runtime dependency-free and preserve caller context cancellation.

## Update the API contract

Generate backend documents with its `npm run openapi:build` command. Commit the intended backend contract before preparing an SDK release. From the SDK repository root, synchronize the generated directory:

```bash
python3 scripts/sync-spec.py /path/to/backend/docs/public-api
```

For development against an uncommitted backend change, add `--allow-dirty`. The resulting provenance records `uncommittedSource: true` and intentionally fails release checks. Do not edit that flag by hand.

Regenerate from each package directory:

| Directory | Command |
| --- | --- |
| `typescript/` | `npm run generate` |
| `python/` | `python scripts/generate.py` |
| `go/` | `go generate ./...` |

Update `spec/type-names.json` when a new inline schema needs a stable shared name. Update `tests/contracts.json` and every language's operation mapping when adding an endpoint. Generated models do not update handwritten endpoint wrappers automatically. Commit the source documents, provenance, generated files, wrapper changes, and fixtures together.

## Submit a change

Open a pull request that explains the user-visible problem, resulting behavior, and checks you ran. Link the originating issue when one exists. Include breaking changes, compatibility implications, and any checks you could not run.

Use deterministic local transports or offline fixtures for tests. Do not include credentials, private League/player data, or production writes in fixtures. Route suspected vulnerabilities through [SECURITY.md](SECURITY.md).

Add a focused entry to `CHANGELOG.md` for changes that affect consumers. Maintainers review API compatibility and release scope before merging; contributing does not require registry or production access.
