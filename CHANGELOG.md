# Changelog

User-visible changes are recorded here before release. TypeScript, Python, and Go publish independently; an entry under **Unreleased** does not mean a registry version is available.

## Unreleased

### Fixed

- TypeScript timeouts and caller cancellation now cover response-body reads and retry waits. Retry timers keep pending Node operations alive.
- TypeScript CommonJS consumers resolve CommonJS declarations. Cached response mutation no longer affects later reads.
- All clients apply retry-delay limits consistently and isolate cache behavior from custom request headers and response variations.
- Python preserves populated mutable defaults in submitted models and handles case-insensitive headers without duplicate authorization values.
- SDK input/protocol errors, Go custom-client timeout classification, cache freshness, and revalidation metadata are more consistent.

### Added

- Shared fixtures covering every documented operation, transport regressions, installed-package consumer checks, and runnable integration examples.
- Explicit spec synchronization with filename mapping, backend revision/hash provenance, and release checks for committed source snapshots.
- Separate build, publishing, and release-note jobs with pinned Actions; prerelease channels and artifact checks for release retries.
- Contributor, support, security-reporting, and release-owner guidance.

### Changed

- Invalid retry/timeout settings and empty explicit idempotency keys now fail before sending requests.
- TypeScript creates League wrappers on demand and snapshots pagination filters/options. Cached responses with `Vary` bypass storage conservatively.
- TypeScript development tooling uses patched esbuild 0.28.1. The published runtime remains dependency-free.
