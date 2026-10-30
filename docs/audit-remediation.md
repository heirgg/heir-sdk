# SDK audit remediation — 30 October 2026

The twelve confirmed defects from the release-readiness audit are addressed in this checkout. New regression tests exercise the failures, and all three SDKs consume the same 24 operation fixtures in `tests/contracts.json`.

| Finding | Resolution | Regression coverage |
| --- | --- | --- |
| TypeScript timeout ended at headers | Keep timeout and cancellation active through body consumption | Delayed/error bodies, aborted body reads, truncated streams |
| Node exited during retry | Keep retry timers referenced until completion/cancellation | Installed-package child process with real timers |
| Python omitted mutated stats | Serialize explicit fields and changed mutable defaults, including current extra fields | Nested stats, explicit null, unchanged defaults, added/deleted extra scores |
| CommonJS declaration mismatch | Separate import/require declaration exports | Installed npm tarball compiled with Node16 and NodeNext resolution |
| Cancellation ignored during backoff | Abort retry waits before another attempt | Abort during wait and no subsequent request |
| Mutable TypeScript cache | Cache serialized data and decode each response | Caller mutation does not affect later reads |
| Errors escaped SDK hierarchy | Add input/protocol errors and defensive envelope parsing | Invalid JSON, invalid model shapes, malformed issues, invalid options |
| Retry delay cap bypassed | Apply the cap to both connection and HTTP-status retries | No sleep/retry beyond the configured cap in all three SDKs |
| Go timeout misclassification | Inspect underlying timeout errors as well as context | Custom HTTP client/transport timeouts |
| Wrong spec copy filename | Explicit sync mapping and source hashes | Accidental filenames, edited snapshots, ignored/uncommitted source files |
| Credential context crossed cache entries | Bypass caching for custom request headers and varying responses | Different authorization contexts and Vary responses |
| Duplicate Python headers | Merge with case-insensitive HTTPX headers | SDK-controlled headers override alternate casing |

Additional fixes cover HTTP Age/Date/no-cache and 304 metadata, bounded cache eviction, validated configuration, safe URL construction, template submission/conversion, pagination cancellation and immutable filters, and oversized/invalid Retry-After values. Python tests exercise both asyncio and Trio. Package checks use actual installed artifacts, including Python's minimum runtime dependency versions.

Release workflows now separate read-only build/test work from publishing and release-note permissions, pin external Actions, verify previously published bytes before resuming, and distinguish prereleases. Shared contract checks and dependency update configuration are part of CI. Contributor, compatibility, security, release, and runnable example documentation is included.

The root README includes the generated [banner](../assets/readme-banner.png). Its source prompt and generation details are recorded in [assets/README.md](../assets/README.md).

## Local verification

- TypeScript: 91 tests, generation freshness, typechecking, build, installed-tarball ESM/CommonJS consumers, retry subprocess, and offline examples passed. The patched npm dependency tree reported no advisories.
- Python: 157 tests across sync/asyncio/Trio, generation freshness, Ruff, strict mypy, wheel and source builds passed. Isolated wheel consumers passed with current dependencies and with Python 3.10 plus the minimum supported runtime dependencies.
- Go: tests with race detection and shuffled execution, generation freshness, vet, formatting, and golangci-lint passed. govulncheck reported no vulnerabilities.
- Shared tooling: 23 tests covering spec integrity, operation coverage, version validation, registry artifact matching, and release-tag ancestry passed. Actionlint, documentation link checks, and whitespace checks passed.

These are local verification results. Check the pull request's current CI results for verification of the committed revision on GitHub-hosted runners.

## Release prerequisites

Source-code remediation is separate from publishing. No packages were published, tags pushed, repository visibility changed, or registry credentials configured during this work.

The existing backend documents are uncommitted in the adjacent checkout. `spec/source.json` records their exact hashes and base revision with `uncommittedSource: true`; release checks deliberately require a committed backend snapshot before publication. This status is evidence about the current snapshot, not a claim that the deployed API is incompatible.

The release owner must finish repository visibility/protection and npm/PyPI ownership/trusted-publisher setup, confirm the intended backend deployment, and run the preflight described in [RELEASING.md](../RELEASING.md). A public Go tag itself releases a module version, so its checks must run before pushing the tag.
