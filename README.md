# Heir SDKs

Official client libraries for the [Heir public API](https://api.heir.gg/public/v1/openapi.json): TypeScript (Node), Go and Python.

Status: pre-release. Nothing here is published yet.

## Layout

```text
spec/        OpenAPI documents the SDKs are generated from (synced from the backend repo, do not edit by hand)
typescript/  @heir/sdk for Node and other JavaScript runtimes
go/          Go module
python/      Python package, sync and async
```

## Source of truth

The backend builds `spec/*.json` from the Zod schemas its routes validate with, so the documents cannot drift from what the API serves. The same documents are served live:

- `https://api.heir.gg/public/v1/openapi.json` for League reads, eligibility and inventory
- `https://api.heir.gg/public/v1/stats/openapi.json` for stat submission (served only while that API is switched on)

To refresh them, run `npm run openapi:build` in the backend repo and copy `docs/public-api/*.json` into `spec/`. Each language's client is regenerated from `spec/`, and CI fails when a committed client is out of date.

## What every client provides

- Bearer authentication with a League developer key, sent only from servers, never from a game client or browser
- Retry on 429 that honours `Retry-After`
- `ETag` / `If-None-Match` handling on reads
- Idempotency keys on stat-submission writes
- Page and `nextToken` pagination helpers
- The API's `{error, message}` envelope surfaced as typed errors
