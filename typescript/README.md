# @heirgg/sdk

The official TypeScript client for the [Heir public API](https://api.heir.gg/public/v1/openapi.json): League players, ratings, Rosters, schedules, results and shop inventory, fixture eligibility checks, and stat submission. Node 20 or later, or a modern runtime with `fetch`, `AbortController`, and `crypto.randomUUID`. ESM and CommonJS, fully typed from the API's own OpenAPI document. Declarations are tested with TypeScript 5.9 using Node16 and NodeNext module resolution.

## Install

```bash
npm install @heirgg/sdk
```

## Read a League

Reads need no key. Without one, each address may make 120 requests a minute across every League.

```ts
import {Heir} from "@heirgg/sdk";

const heir = new Heir();
const nacl = heir.league("nacl"); // vanity name or Discord server ID

const {player} = await nacl.player("mordhau", "A1B2C3D4E5F67890");
if (player) console.log(player.displayName, player.mmr?.value, player.rank?.name);

const {players} = await nacl.lookupPlayers({credential: "steam", identifiers: ["76561198000000000"]});
const {items} = await nacl.inventory("mordhau", "A1B2C3D4E5F67890");
const config = await nacl.config();
```

Answers the API marks cacheable are kept for its `max-age`, reduced by `Age` and the response's apparent age, then revalidated with `ETag`. `no-cache` forces revalidation and `no-store` prevents storage. The SDK conservatively bypasses caching for responses with any `Vary` value and calls with custom headers. A cached result is decoded separately for each caller, so changing a returned object never changes future results. Pass `cache: false` to the client, or to one call, to always ask.

## Use a developer key

A League Organizer creates a developer key under Manage League, Developer. With it, reads of that League draw on the plan's allowance instead of the per-address limit, eligibility checks work, and stat submission is available. Call from your server. Never put a key in a game client or a browser.

```ts
const heir = new Heir({apiKey: process.env.HEIR_API_KEY});

const verdicts = await heir.league("nacl").checkEligibility({
  credential: "mordhau", fixtureId, rosterId, gamemode: "SKM", identifiers: playfabIds
});
```

## Lists

A list call returns a `Page`: its rows in `items`, the whole answer in `body`, and `next()` for the page after. Iterating a page with `for await` walks it and every page after it, with the same filters.

```ts
const first = await nacl.rosters({category: "competitive", pageSize: 50});
console.log(first.items.length, first.hasMore);

for await (const roster of first) console.log(roster.name, roster.teamMmr);

const board = await nacl.leaderboard({metric: "heirRating"});
console.log(board.body.snapshotAt, board.items[0]);
```

Pagination captures the original filters and options. A live cursor expires after 30 minutes; leaderboard/standings snapshots last five minutes. On HTTP 410, restart from the first page and deduplicate by your application's stable item ID if work has already been processed. An `AbortSignal` supplied to the first call also governs subsequent pages.

## Submit stats

Requires a key whose gamemode permissions include the gamemode. Any gamemode a League plays can be sent as one finished `heir-match-v1` document. Set `reference` to your own id for the match: a repeat with the same contents is a no-op, and the SDK will then also resend it after a connection failure.

```ts
const receipt = await heir.stats.submitMatch({
  format: "heir-match-v1",
  gamemode: {key: "SKM"},
  type: "pug",
  reference: "lobby-42-2026-10-16-1900",
  startedAt: "2026-10-16T19:00:00Z",
  maps: [{map: "Camp", winner: "a", score: {a: 7, b: 4}, players: [
    {identity: "A1B2C3D4E5F67890", name: "Ada", side: "a", stats: {kills: 18, deaths: 9, score: 2140}},
    {identity: "0F1E2D3C4B5A6978", name: "Brann", side: "b", stats: {kills: 11, deaths: 15, score: 1310}}
  ]}]
});
console.log(receipt.status, receipt.problems);
```

Persist `reference` alongside the exact document before sending it. After a connection failure or a producer restart, resend the same document and reference. Changing the content under an existing reference is a conflict. Omitted statistics mean unmeasured; only send zero when zero was measured (built-in core counters may default to zero on the API). Complete-match timestamps are ISO strings; tracking timestamps such as `startedAt` are integer milliseconds, not seconds.

Team matches can also be tracked live, a round at a time. Every tracking write carries an `Idempotency-Key`. The SDK generates one per call so its own retries never write twice; pass `idempotencyKey` yourself when your code may send the same request again later.

```ts
const {approval} = await heir.stats.beginMatch({matchId: "lobby-42", startedAt: Date.now()});
await heir.stats.appendUnits("lobby-42", {games: [{schemaRef: "mordhau.skirmish@1", gameId: "map-1", map: "Camp", rounds: [round]}]},
  {idempotencyKey: "lobby-42:map-1:round-0"});
await heir.stats.heartbeat("lobby-42");
const {status, heldForReview} = await heir.stats.finalize("lobby-42");

// Or check a request without storing anything:
await heir.stats.appendUnits("lobby-42", units, {dryRun: true});
```

`heir.stats.gamemodes()` lists the gamemodes a key may submit with their stat keys and an empty document to fill in; `heir.stats.schemas()` lists the tracking schemas and every counter a Player line may carry.

The catalog's `template` can be assigned directly to `HeirMatchFile`. Copy it, fill it with actual results and identities, and persist it before submission. For tracking, persist every batch payload and a distinct idempotency key before sending; reuse that key only for that same payload. Heartbeats need a new key for each new heartbeat, while retries of one heartbeat reuse its key. A complete tracked upload with `{dryRun: true}` validates all units without opening a live session.

## Errors

SDK errors extend `HeirError`. Caller-initiated cancellation rethrows the signal's reason unchanged. `HeirInputError` reports invalid configuration, headers, path parameters, or JSON encoding; `HeirProtocolError` reports successful responses that are invalid JSON or not JSON objects. Generated types describe the full schema at compile time; the SDK does not perform full runtime response-schema validation. The API validates request fields and returns `HeirApiError` for rejected data.

```ts
import {HeirApiError, HeirConnectionError, HeirTimeoutError} from "@heirgg/sdk";

try {
  await nacl.player("mordhau", id);
} catch (error) {
  if (error instanceof HeirApiError) {
    // error.code is the stable code to branch on; error.message is a sentence for a person.
    if (error.code === "league-not-found") { /* ... */ }
    if (error.isRateLimited) console.log("wait", error.retryAfter, "seconds");
    console.log(error.status, error.issues);
  } else if (error instanceof HeirTimeoutError) {
    // no answer within timeoutMs
  } else if (error instanceof HeirConnectionError) {
    // could not reach the API; error.cause has the underlying failure
  }
}
```

The SDK retries a 429 or 503 up to `maxRetries` times (default 2), waiting as `Retry-After` says or with increasing backoff. Reads, and writes that carry an idempotency key, are also retried after a connection failure (including an interrupted response body) or a gateway error. Timed-out attempts are not retried. Any retry delay longer than `maxRetryDelayMs` (default 30 s) rejects the retry and throws the error; it is not shortened. API errors expose `retryAfter` so your code can decide. Cancelling the caller's signal interrupts both body reads and retry waits.

## Options

```ts
new Heir({
  apiKey,                 // a League developer key; leave out to read without one
  baseUrl,                // default https://api.heir.gg
  fetch,                  // your own fetch (proxy, agent, tests)
  maxRetries: 2,
  maxRetryDelayMs: 30_000,
  timeoutMs: 30_000,      // per attempt, including reading the response body
  cache: true,            // honour Cache-Control and ETag on League reads
  userAgent: "my-server/1.0"
});
```

Every call also takes `{signal, headers, maxRetries, timeoutMs, cache}` as its last argument.

`maxRetries` must be a nonnegative safe integer, `maxRetryDelayMs` a finite nonnegative number, and `timeoutMs` positive. Both millisecond options must be at most 2,147,483,647, the runtime timer limit. Use `signal: AbortSignal.timeout(60_000)` to limit the entire operation, including retries; the client timeout applies to each attempt. SDK-controlled Accept, Content-Type, User-Agent, constructor Authorization, and generated Idempotency-Key headers take precedence over custom headers, regardless of casing. Empty explicit idempotency keys are rejected before sending.

To rotate credentials, construct a new client with the replacement key and move new work to it. Constructor configuration is immutable. Keep developer keys on your server, scoped to the League and gamemodes the integration needs.

## Runnable examples

From this repository, run `npm ci && npm run build` in `typescript/`, then:

```bash
node examples/public-read.mjs
node examples/eligibility.mjs
node examples/submit-match.mjs
node examples/tracking.mjs
```

All four run offline with shared fixtures by default. They cover reads/pagination, fixture eligibility, catalog discovery and complete-match submission, and persisted tracking requests with repeatable keys. The [example sources](https://github.com/heirgg/heir-sdk/tree/main/typescript/examples) also show per-operation deadlines.

To contact an API, deliberately supply `--live` and set `HEIR_BASE_URL` to its URL; authenticated examples also require `HEIR_API_KEY`. `HEIR_LEAGUE` selects the League for read examples. Supply your real request with `--file request.json`. The complete-match example only previews until `--submit` is added. The tracking example uses a dry-run upload until `--submit` is added; then it begins, appends, heartbeats, and finalizes. The input tracking journal contains `matchId`, millisecond `startedAt`, and `games` with actual units/results. Never use fixture data as real match statistics.

## Types

All request and response types are exported by the names the API document gives them: `Player`, `Roster`, `Fixture`, `LeaderboardEntry`, `HeirMatchFile`, `MatchEntryReceipt`, `BeginMatchResponse`, and so on. The raw generated `paths` and `operations` are exported as `PublicPaths`, `PublicOperations`, `StatPaths` and `StatOperations` for use with other OpenAPI tooling.

## Developing

```bash
npm install
npm run generate   # src/generated from ../spec
npm test
npm run test:package   # build, install the tarball offline, compile/run consumers, run offline examples
```

`src/generated` is written from `../spec` by `npm run generate` and checked in; CI fails when it is out of date.

The tests also exercise all operations using `../tests/contracts.json`. Package checks cover ESM and CommonJS declarations/runtime imports and a real-timer child process to catch retry-lifecycle regressions. The pinned esbuild override patches GHSA-g7r4-m6w7-qqqr in development tooling without changing the public SDK's dependency-free runtime; revisit it when upgrading tsup to a version that requests the patched release itself.
