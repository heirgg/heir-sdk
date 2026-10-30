![Heir SDK](assets/readme-banner.png)

# Integrate Heir into your project

Official SDKs for reading Heir League data, checking fixture eligibility, and submitting match statistics. Choose TypeScript, Python, or Go; each client handles authentication, retries, pagination, and conditional caching.

| Language | Package | Runtime | Integration guide |
| --- | --- | --- | --- |
| TypeScript / JavaScript | `@heirgg/sdk` | Node 20+; modern Fetch runtimes | [TypeScript](typescript/README.md) |
| Python | `heir-sdk`, imported as `heir` | Python 3.10+ | [Python](python/README.md) |
| Go | `github.com/heirgg/heir-sdk/go` | Go 1.23+ | [Go](go/README.md) |

The repository is preparing its first public release. Registry publishing and public repository access require release-owner setup. The current [contract provenance](spec/source.json) records an uncommitted backend snapshot; release checks block publishing until it is replaced by a committed source snapshot. Follow [local setup](CONTRIBUTING.md) to work from this checkout.

## Read a League

Public reads need no developer key. After the TypeScript package is published, install it with `npm install @heirgg/sdk` and read a player:

```typescript
import {Heir} from "@heirgg/sdk";

const client = new Heir();
const league = client.league("nacl");
const {player} = await league.player("mordhau", "A1B2C3D4E5F67890");

if (player) console.log(player.displayName, player.mmr?.value);
for await (const roster of await league.rosters()) {
  console.log(roster.name, roster.teamMmr);
}
```

League reads cover players, ratings, rosters, standings, fixtures, match results, and shop inventory. An unlinked or departed player can produce a successful response with `player: null`.

## Authenticate and submit statistics

A League Organizer creates a developer key under Manage League → Developer and selects its gamemode permissions. Keep the key on your server. Eligibility checks and stat submission require it; never include it in browser or game-client bundles.

Choose the submission flow that matches your integration:

- **Finished match**: send a `heir-match-v1` document. Persist a stable `reference` and reuse it with identical contents when recovering from a lost connection.
- **Live tracking**: begin a match, append units, send heartbeats, and finalize. Persist an idempotency key for each distinct request and reuse it for retries of that request.
- **Validation**: tracking writes and complete tracked uploads accept `dryRun`. Complete-match document submission has no dry-run option.

Use catalog endpoints to discover allowed gamemodes, schemas, and stat names. See the language guides for runnable examples, error handling, timestamp formats, cancellation, and recovery.

## Understand the API contract

The SDKs generate types/models from checked-in backend documents. [spec/source.json](spec/source.json) records their backend commit, hashes, and whether the source documents were uncommitted. This identifies a source snapshot; it does not prove that a deployment serves that version.

The API also serves a [public OpenAPI document](https://api.heir.gg/public/v1/openapi.json) and a [stat-submission document](https://api.heir.gg/public/v1/stats/openapi.json), when stat submission is enabled. Compare your intended backend release before relying on a new field or operation.

To refresh the snapshot, generate the documents in the backend, then run the sync command from this repository:

```bash
python3 scripts/sync-spec.py /path/to/backend/docs/public-api
python3 scripts/sync-spec.py --check
python3 scripts/check-contracts.py
```

The sync script maps backend `openapi.json` to `spec/public-openapi.json`, copies the other three documents, and records provenance. Do not copy `*.json` manually. Follow [the generation workflow](CONTRIBUTING.md#update-the-api-contract) to regenerate each SDK and update shared fixtures.

## Contribute and get support

Use [CONTRIBUTING.md](CONTRIBUTING.md) for setup and checks, [SUPPORT.md](SUPPORT.md) for compatibility and troubleshooting, and [SECURITY.md](SECURITY.md) for private vulnerability reporting. Package releases use independent version tags; maintainers follow [RELEASING.md](RELEASING.md). Changes awaiting release appear in [CHANGELOG.md](CHANGELOG.md).

The source and each language package use the [MIT license](LICENSE).
