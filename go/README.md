# heir (Go)

The official Go client for the [Heir public API](https://api.heir.gg/public/v1/openapi.json): League players, ratings, Rosters, schedules, results and shop inventory, fixture eligibility checks, and stat submission. Go 1.23 or later, no dependencies beyond the standard library. Every type is generated from the API's own OpenAPI document.

```bash
go get github.com/heirgg/heir-sdk/go
```

```go
import heir "github.com/heirgg/heir-sdk/go"
```

## Read a League

Reads need no key. Without one, each address may make 120 requests a minute across every League.

```go
client := heir.NewClient()
nacl := client.League("nacl") // vanity name or Discord server ID

answer, err := nacl.Player(ctx, "mordhau", "A1B2C3D4E5F67890", nil)
if err != nil { return err }
if answer.Player != nil {
	fmt.Println(answer.Player.DisplayName, answer.Player.MMR, answer.Player.Rank)
}

lookup, err := nacl.LookupPlayers(ctx, heir.PlayerLookupRequest{Credential: "steam", Identifiers: []string{"76561198000000000"}})
inventory, err := nacl.Inventory(ctx, "mordhau", "A1B2C3D4E5F67890", nil)
config, err := nacl.Config(ctx)
```

A nullable field is a pointer: `answer.Player` is nil for an identity Heir does not know. Answers the API marks cacheable are kept for the minute it allows and revalidated with `ETag` after that, so asking on every join or every event costs one request a minute per question. `heir.WithoutCache()` on the client, or `heir.NoCache()` on one call, always asks.

## Use a developer key

A League Organizer creates a developer key under Manage League, Developer. With it, reads of that League draw on the plan's allowance instead of the per-address limit, eligibility checks work, and stat submission is available. Call from your server. Never put a key in a game client or a browser.

```go
client := heir.NewClient(heir.WithAPIKey(os.Getenv("HEIR_API_KEY")))

verdicts, err := client.League("nacl").CheckEligibility(ctx, heir.EligibilityRequest{
	Credential: "mordhau", FixtureID: fixtureID, RosterID: rosterID, Gamemode: "SKM", Identifiers: playfabIDs,
})
```

## Lists

A list call returns a `Page`: its rows in `Items`, the whole answer in `Body`, and `Next` for the page after. `All` walks this page and every page after it, with the same filters.

```go
first, err := nacl.Rosters(ctx, &heir.RostersQuery{Category: heir.CategoryCompetitive, PageSize: 50})
fmt.Println(len(first.Items), first.HasMore())

for roster, err := range first.All(ctx) {
	if err != nil { return err }
	fmt.Println(roster.Name, roster.TeamMMR)
}

board, err := nacl.Leaderboard(ctx, &heir.LeaderboardQuery{Metric: heir.MetricHeirRating})
fmt.Println(board.Body.SnapshotAt, board.Items[0])
```

A nil query means the API's defaults.

## Submit stats

Requires a key whose gamemode permissions include the gamemode. Any gamemode a League plays can be sent as one finished `heir-match-v1` document. Set `Reference` to your own id for the match: a repeat with the same contents is a no-op, and the client will then also resend it after a connection failure. Timestamps may carry at most millisecond precision, so truncate a `time.Now()`.

```go
reference, gamemode, matchType := "lobby-42-2026-10-16-1900", "SKM", heir.MatchTypePug
ada, brann, a, b := "A1B2C3D4E5F67890", "0F1E2D3C4B5A6978", "a", "b"
n := func(v float64) *float64 { return &v }

receipt, err := client.Stats.SubmitMatch(ctx, heir.HeirMatchFile{
	Format:    heir.HeirMatchFormatHeirMatchV1,
	Gamemode:  &heir.HeirMatchGamemode{Key: &gamemode},
	Type:      &matchType,
	Reference: &reference,
	StartedAt: time.Date(2026, 10, 16, 19, 0, 0, 0, time.UTC),
	Maps: []heir.HeirMatchMap{{
		Winner: &a, Score: &heir.HeirMatchScore{A: 7, B: 4},
		Players: []heir.HeirMatchPlayer{
			{Identity: &ada, Side: &a, Stats: map[string]*float64{"kills": n(18), "deaths": n(9), "score": n(2140)}},
			{Identity: &brann, Side: &b, Stats: map[string]*float64{"kills": n(11), "deaths": n(15), "score": n(1310)}},
		},
	}},
})
fmt.Println(receipt.Status, receipt.Problems)
```

Team matches can also be tracked live, a round at a time. Every tracking write carries an `Idempotency-Key`. The client generates one per call so its own retries never write twice; pass `heir.WithIdempotencyKey` when your code may send the same request again later.

```go
begun, err := client.Stats.BeginMatch(ctx, heir.BeginMatchRequest{MatchID: "lobby-42", StartedAt: time.Now().UnixMilli()})
_, err = client.Stats.AppendUnits(ctx, "lobby-42", heir.AppendUnitsRequest{Games: []heir.GameSubmission{{
	SchemaRef: "mordhau.skirmish@1", GameID: "map-1", Rounds: []heir.RoundUnit{round},
}}}, heir.WithIdempotencyKey("lobby-42:map-1:round-0"))
_, err = client.Stats.Heartbeat(ctx, "lobby-42")
done, err := client.Stats.Finalize(ctx, "lobby-42")

// Or check a request without storing anything:
_, err = client.Stats.AppendUnits(ctx, "lobby-42", units, heir.DryRun())
```

`client.Stats.Gamemodes` lists the gamemodes a key may submit with their stat keys and an empty document to fill in; `client.Stats.Schemas` lists the tracking schemas and every counter a Player line may carry.

## Errors

```go
answer, err := nacl.Player(ctx, "mordhau", id, nil)
var apiErr *heir.APIError
var connErr *heir.ConnectionError
switch {
case errors.As(err, &apiErr):
	// apiErr.Code is the stable code to branch on; apiErr.Message is a sentence for a person.
	if apiErr.Code == "league-not-found" { /* ... */ }
	if apiErr.IsRateLimited() { fmt.Println("wait", apiErr.RetryAfter) }
	fmt.Println(apiErr.StatusCode, apiErr.Issues)
case errors.As(err, &connErr):
	// could not reach the API (connErr.Err), or no answer in time (connErr.Timeout)
case errors.Is(err, context.Canceled):
	// your own context
}
```

The client retries a 429 or 503 up to `WithMaxRetries` times (default 2), waiting as `Retry-After` says or with increasing backoff. Reads, and writes that carry an idempotency key, are also retried after a connection failure or a gateway error. A `Retry-After` longer than `WithMaxRetryDelay` (default 30 s) is not waited for: the error is returned with `RetryAfter` set so your code can decide.

## Options

```go
heir.NewClient(
	heir.WithAPIKey(key),                  // a League developer key; leave out to read without one
	heir.WithBaseURL("https://api.heir.gg"),
	heir.WithHTTPClient(httpClient),       // your own transport, proxy or fake
	heir.WithMaxRetries(2),
	heir.WithMaxRetryDelay(30*time.Second),
	heir.WithTimeout(30*time.Second),      // per attempt; the context still rules
	heir.WithoutCache(),
	heir.WithUserAgent("my-server/1.0"),
)
```

Every call also takes options: `heir.WithHeader`, `heir.NoCache`, and for tracking writes `heir.WithIdempotencyKey` and `heir.DryRun`.

## Developing

```bash
go generate ./...   # types_*.gen.go from ../spec
go test ./...
```

`types_public.gen.go` and `types_stats.gen.go` are written from `../spec` by `internal/gen`, which uses oapi-codegen for models and first names the document's inline shapes; CI fails when they are out of date.
