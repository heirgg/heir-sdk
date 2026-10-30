package heir_test

import (
	"context"
	"errors"
	"fmt"
	"os"
	"time"

	heir "github.com/heirgg/heir-sdk/go"
)

// The examples compile with the tests, so the README's usage cannot drift from the API. They do not run.

func ExampleClient_League() {
	ctx := context.Background()
	client := heir.NewClient()
	nacl := client.League("nacl")

	answer, err := nacl.Player(ctx, "mordhau", "A1B2C3D4E5F67890", &heir.PlayerQuery{Category: heir.CategoryCompetitive})
	if err != nil {
		var apiErr *heir.APIError
		if errors.As(err, &apiErr) && apiErr.IsRateLimited() {
			fmt.Println("wait", apiErr.RetryAfter)
		}
		return
	}
	if answer.Player != nil {
		fmt.Println(answer.Player.DisplayName)
	}
}

func ExamplePage_All() {
	ctx := context.Background()
	nacl := heir.NewClient().League("nacl")
	first, err := nacl.Rosters(ctx, &heir.RostersQuery{Category: heir.CategoryCompetitive, PageSize: 50})
	if err != nil {
		return
	}
	for roster, err := range first.All(ctx) {
		if err != nil {
			return
		}
		fmt.Println(roster.Name, roster.TeamMMR)
	}
}

func ExampleStats_SubmitMatch() {
	ctx := context.Background()
	client := heir.NewClient(heir.WithAPIKey(os.Getenv("HEIR_API_KEY")))
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
	if err != nil {
		return
	}
	fmt.Println(receipt.Status, receipt.Problems)
}

func ExampleStats_BeginMatch() {
	ctx := context.Background()
	client := heir.NewClient(heir.WithAPIKey(os.Getenv("HEIR_API_KEY")))
	if _, err := client.Stats.BeginMatch(ctx, heir.BeginMatchRequest{MatchID: "lobby-42", StartedAt: time.Now().UnixMilli()}); err != nil {
		return
	}
	round := heir.RoundUnit{Index: 0, Players: []map[string]interface{}{{"playfabId": "A1B2C3D4E5F67890", "side": 0, "kills": 2, "deaths": 0, "teamKills": 0, "suicides": 0, "score": 240}}}
	units := heir.AppendUnitsRequest{Games: []heir.GameSubmission{{SchemaRef: "mordhau.skirmish@1", GameID: "map-1", Rounds: []heir.RoundUnit{round}}}}
	if _, err := client.Stats.AppendUnits(ctx, "lobby-42", units, heir.WithIdempotencyKey("lobby-42:map-1:round-0")); err != nil {
		return
	}
	if _, err := client.Stats.AppendUnits(ctx, "lobby-42", units, heir.DryRun()); err != nil {
		return
	}
	done, err := client.Stats.Finalize(ctx, "lobby-42")
	if err != nil {
		return
	}
	fmt.Println(done.Status, done.HeldForReview)
}

func ExampleMatchTemplate_ToMatchFile() {
	// In an integration, get this template from client.Stats.Gamemodes(ctx).
	template := heir.MatchTemplate{Format: heir.HeirMatchFormatHeirMatchV1}
	file := template.ToMatchFile()
	reference := "game-server-match-42"
	file.Reference = &reference
	file.StartedAt = time.Date(2026, 10, 30, 12, 0, 0, 0, time.UTC)
	fmt.Println(file.Format, *file.Reference, file.StartedAt.Format(time.RFC3339))
	// Add the match's players and results to file.Maps, then call client.Stats.SubmitMatch(ctx, file).
	// Output: heir-match-v1 game-server-match-42 2026-10-30T12:00:00Z
}
