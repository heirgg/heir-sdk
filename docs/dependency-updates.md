# Dependency refresh — 30 October 2026

Versions were checked against the official npm, PyPI, Go module, and GitHub release registries. The refresh selects the newest stable versions that work together; documented generator and interpreter constraints are retained where a newer version demonstrably breaks compatibility.

## TypeScript

| Dependency | Selected version |
| --- | --- |
| TypeScript checker | 7.0.2 |
| Node type definitions | 26.6.6 |
| Vitest | 5.0.5 |
| tsup | 9.0.0 |
| esbuild | 0.28.2, resolved normally without an override |
| openapi-typescript | 7.13.0, current stable |

The primary project uses native TypeScript 7. Generation and declaration bundling are isolated in the private [build-tools project](../typescript/tools/codegen/README.md), which retains TypeScript 5.9.3 because the current generator requires its JavaScript compiler API and declares a `^5.x` peer. This avoids the peer conflict in the standalone TypeScript 7 Dependabot update without forcing an invalid dependency graph. Both projects have lockfiles, vulnerability checks, and separate Dependabot entries.

Development tools run on current supported Node 22, 24 and 26 releases. CI also installs and runs the built SDK on Node 20, without trying to run the newer development tools there. Public runtime support and the dependency-free SDK bundle are preserved.

## Python

| Dependency | Latest tested version |
| --- | --- |
| AnyIO | 4.15.1; supported minimum raised to 4.14.2 for security fixes |
| HTTPX | 0.28.1 |
| Pydantic | 2.14.2 |
| Hatchling | 1.33.0 |
| Build frontend | 1.6.1 |
| pytest | 9.2.0 |
| datamodel-code-generator | 0.87.0, current stable |
| Ruff | 0.17.3 |
| mypy | 2.4.1 |
| Trio | 0.34.0 |
| pip-audit | 2.10.1 |

[requirements-dev.txt](../python/requirements-dev.txt) records the full resolved toolchain, including transitive dependencies and Python/platform markers. CI and release builds use these constraints and build without a second isolated dependency resolution. Public runtime dependency ranges stay compatible; installed-wheel checks separately exercise the supported minimum versions.

The generator requires `isort<9`, so 8.0.1 is the newest compatible release. Python 3.10 uses the newest compatible versions of a few tooling dependencies whose newer releases require Python 3.11. The audit tool itself runs on Python 3.11+ so that its cache dependency can use patched filelock releases instead of the vulnerable older chain. See the [Python maintenance notes](../python/README.md#dependency-maintenance).

## Go

The runtime remains standard-library-only at Go 1.23. The generator now requires Go 1.26 and updates 15 explicitly selected transitive dependencies. Its direct libraries, kin-openapi 0.152.0 and oapi-codegen 2.8.1, were already current.

Three transitive libraries retain verified YAML API compatibility limits:

- `speakeasy-api/openapi`: 1.25.6; newer releases change the public YAML node type.
- `speakeasy-api/jsonpath`: 0.6.3; 0.7 changes the same API.
- `dprotaso/go-yit`: `v0.0.0-20250513224043-18a80f8f6df4`; later revisions migrate the node type used by the current JSONPath dependency.

Newer versions fail compilation with the latest stable generator. The [generator README](../go/internal/gen/README.md) links the upstream changes and documents the coordinated update procedure. Dependabot suppresses these incompatible ranges while vulnerability scans continue covering the generator. Unused entries appearing only in upstream module metadata are not added as unnecessary direct pins.

## CI and review

Every GitHub Action pin was rechecked against its latest official stable release; the existing SHA pins were already current. golangci-lint 2.15.0 and govulncheck 1.9.0 were also current.

Validation covers generated-file freshness, native and compatibility TypeScript declarations, installed ESM/CommonJS consumers, Node 20 runtime behavior, sync/async Python on current and minimum dependencies, both Go modules, and dependency advisory scans. The consolidated update incorporates the upgrades proposed by Dependabot PRs #2, #4, #5, #6 and #7; redundant PRs can be closed once this change is merged and their proposed updates are present on main.
