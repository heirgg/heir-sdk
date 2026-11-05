# Changelog

User-visible changes are recorded here before release. TypeScript, Python, and Go publish independently; an entry under **Unreleased** does not mean a registry version is available.

## Unreleased

### Fixed

- TypeScript timeouts and caller cancellation now cover response-body reads and retry waits. Retry timers keep pending Node operations alive.
- TypeScript CommonJS consumers resolve CommonJS declarations. Cached response mutation no longer affects later reads.
- All clients apply retry-delay limits consistently and isolate cache behavior from custom request headers and response variations.
- Python reads and sends a documented number (match and Player stats, leaderboard values, Heir Rating) as `int | float`, so a whole number stays `10` rather than becoming `10.0`. Go keeps `float64`, which encodes a whole value without a fraction.
- Python preserves populated mutable defaults in submitted models and handles case-insensitive headers without duplicate authorization values.
- SDK input/protocol errors, Go custom-client timeout classification, cache freshness, and revalidation metadata are more consistent.

### Added

- League config models include `recognition`, Heir's verified or official mark for a League. Player reads, lookups and eligibility verdicts include `canonicalIdentifier`.
- Python `heartbeat` and `finalize` (sync and async) accept `dry_run`, as every other tracking write does; the API has always accepted it there.
- Shared fixtures covering every documented operation, transport regressions, installed-package consumer checks, and runnable integration examples.
- Explicit spec synchronization with filename mapping, backend revision/hash provenance, and release checks for committed source snapshots.
- Separate build, publishing, and release-note jobs with pinned Actions; prerelease channels and artifact checks for release retries.
- Contributor, support, security-reporting, and release-owner guidance.

### Changed

- Models are generated from the backend's current documents, which write most bodies inline; `spec/type-names.json` names each body by operation so the existing type names are kept. Whole-number fields (pagination, standings, scores, season, `batchMax`) stay integers in Go and Python, and the stat tracking answers (`StatSchemaCatalog`, `BeginMatchResponse`, `AppendUnitsResponse`, `HeartbeatMatchResponse`, `FinalizeMatchResponse`, `UploadMatchResponse`) keep their fields, now taken from the backend's documented answers.
- MMR fields (`mmr.value`, history `mmrBefore`/`mmrAfter`/`mmrDelta`, Roster and standings `teamMmr`) are integers in Go and Python, as the API always rounds them. No SDK has been released, so no published type changes.
- Match detail of an official result includes the per-map Player stats of the tracked matches and recordings that settled it, and names a linked Player by their Heir name while they are a Member of the League. Its `stats` are documented as counters for built-in gamemodes and stat keys for custom ones.
- Invalid retry/timeout settings and empty explicit idempotency keys now fail before sending requests.
- TypeScript creates League wrappers on demand and snapshots pagination filters/options. Cached responses with `Vary` bypass storage conservatively.
- TypeScript uses the native TypeScript 7 checker, Vitest 5, tsup 9, and patched esbuild 0.28.2. Compiler-API generation tools are isolated from the primary checker; the published runtime remains dependency-free and supports Node 20.
- Python requires AnyIO 4.14.2 or newer for upstream security fixes. Its development and build dependencies now use a universal, tested constraints file while retaining Python 3.10 support.
