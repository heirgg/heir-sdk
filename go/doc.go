// Package heir is the official Go client for the Heir public API: League players, ratings, Rosters, schedules,
// results and shop inventory, fixture eligibility checks, and stat submission.
//
//	client := heir.NewClient(heir.WithAPIKey(os.Getenv("HEIR_API_KEY")))
//	nacl := client.League("nacl")
//	answer, err := nacl.Player(ctx, "mordhau", "A1B2C3D4E5F67890", nil)
//
// Reads work without a key. Eligibility checks and stat submission need the League's developer key. The types in
// types_*.gen.go are generated from the API's OpenAPI documents in ../spec by `go generate`.
package heir

//go:generate go run -C internal/gen .
