// Command player reads a League player using the same SDK calls a game server can use on player join.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"

	heir "github.com/heirgg/heir-sdk/go"
)

func main() {
	league := flag.String("league", "nacl", "League vanity name or Discord server ID")
	credential := flag.String("credential", "mordhau", "linked game-account credential")
	identifier := flag.String("id", "", "player's linked game-account identifier")
	flag.Parse()
	if *identifier == "" {
		fmt.Fprintln(os.Stderr, "usage: go run ./examples/player -league nacl -credential mordhau -id YOUR_PLAYER_ID")
		os.Exit(2)
	}
	client := heir.NewClient(heir.WithAPIKey(os.Getenv("HEIR_API_KEY")), heir.WithUserAgent("player-example/1.0"))
	if err := client.Validate(); err != nil {
		fail(err)
	}
	// The context limits the entire operation, including retries and any backoff waits.
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	answer, err := client.League(*league).Player(ctx, *credential, *identifier, nil)
	if err != nil {
		fail(err)
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(answer); err != nil {
		fail(err)
	}
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, err)
	os.Exit(1)
}
