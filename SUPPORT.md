# Get help with an integration

Start with the [TypeScript](typescript/README.md), [Python](python/README.md), or [Go](go/README.md) guide. For a reproducible SDK problem, open a [bug report](https://github.com/heirgg/heir-sdk/issues/new?template=bug_report.yml). For integration questions, use the [integration help form](https://github.com/heirgg/heir-sdk/issues/new?template=integration_help.yml).

## Supported environments and versions

| SDK | Minimum runtime | CI coverage |
| --- | --- | --- |
| TypeScript | Node 20 | Tooling on Node 22, 24, 26; installed-package checks on Node 20; TypeScript 5.9 and native 7 declarations |
| Python | Python 3.10 | Python 3.10, 3.13, current 3.x; asyncio and Trio |
| Go | Go 1.23 | Go 1.23 and current stable; race detector |

Modern Fetch runtimes can use the TypeScript client, but browser, Bun, and Deno combinations are not included in this CI matrix. Use public reads in browsers; developer keys belong on servers.

Each language has its own version and release schedule. Before 1.0, breaking changes may appear in a minor version; patch releases should preserve the public API. After 1.0, incompatible public API changes require a major version. When practical, deprecated APIs remain through the current minor line before removal in a documented breaking release. There is no fixed long-term support or backport commitment.

## Diagnose a failed request

Collect the package version, runtime, operation, HTTP status, stable API error code, and a sanitized reproduction. Retain request IDs from response headers when available. Never include bearer tokens or complete private payloads.

Common cases have different recovery steps:

- **Unknown player**: `player: null` can be a valid response for an unlinked or departed identity.
- **401 or 403**: check that the server uses the intended League key and that it grants the requested gamemode.
- **429**: inspect `retryAfter` and your League allowance. The SDK does not wait beyond its configured maximum retry delay.
- **503**: check service availability and whether stat submission is enabled for the League.
- **410 during pagination**: restart without the continuation token; deduplicate previously processed rows when necessary.
- **Timeout or cancelled request**: distinguish per-attempt transport timeout from your application's overall deadline. Persist write references/keys before retrying after a restart.
- **Protocol/model error**: capture sanitized response metadata and compare the intended backend release with `spec/source.json`.

Response schemas come from a versioned source snapshot, which may differ from the running backend. Generated-file checks verify the repository snapshot; they do not test a deployment.

## Request a change

Describe the integration you are building and the limitation you encountered in a [feature request](https://github.com/heirgg/heir-sdk/issues/new?template=feature_request.yml). Include the affected languages and the public API behavior you need. Keep security reports private using [SECURITY.md](SECURITY.md).
