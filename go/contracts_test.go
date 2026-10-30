package heir

import (
	"context"
	"encoding/json"
	"os"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestSharedOperationContracts(t *testing.T) {
	raw, err := os.ReadFile("../tests/contracts.json")
	if os.IsNotExist(err) {
		t.Skip("shared fixtures are available in the repository checkout")
	}
	if err != nil {
		t.Fatal(err)
	}
	var fixtures struct {
		Cases []struct {
			OperationID  string          `json:"operationId"`
			Method       string          `json:"method"`
			Path         string          `json:"path"`
			RequestBody  json.RawMessage `json:"requestBody"`
			ResponseBody json.RawMessage `json:"responseBody"`
		} `json:"cases"`
	}
	if err := json.Unmarshal(raw, &fixtures); err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	const credential, identifier, id = "mordhau", "A1B2C3D4E5F67890", "9f6d2a70-0000-4000-8000-000000000000"
	type invoke func(*testing.T, *Client, json.RawMessage) (any, error)
	calls := map[string]invoke{
		"getLeaguePlayer": func(t *testing.T, c *Client, b json.RawMessage) (any, error) {
			return c.League("nacl").Player(ctx, credential, identifier, nil)
		},
		"lookupLeaguePlayers": func(t *testing.T, c *Client, b json.RawMessage) (any, error) {
			return c.League("nacl").LookupPlayers(ctx, contractBody[PlayerLookupRequest](t, b))
		},
		"getLeaguePlayerStats": func(t *testing.T, c *Client, b json.RawMessage) (any, error) {
			return c.League("nacl").PlayerStats(ctx, credential, identifier, nil)
		},
		"getLeaguePlayerMatches": func(t *testing.T, c *Client, b json.RawMessage) (any, error) {
			return contractPage(c.League("nacl").PlayerMatches(ctx, credential, identifier, nil))
		},
		"listLeagueRosters": func(t *testing.T, c *Client, b json.RawMessage) (any, error) {
			return contractPage(c.League("nacl").Rosters(ctx, nil))
		},
		"getLeagueRoster": func(t *testing.T, c *Client, b json.RawMessage) (any, error) {
			return c.League("nacl").Roster(ctx, id, nil)
		},
		"getLeagueLeaderboard": func(t *testing.T, c *Client, b json.RawMessage) (any, error) {
			return contractPage(c.League("nacl").Leaderboard(ctx, nil))
		},
		"getLeagueStandings": func(t *testing.T, c *Client, b json.RawMessage) (any, error) {
			return contractPage(c.League("nacl").Standings(ctx, nil))
		},
		"listLeagueFixtures": func(t *testing.T, c *Client, b json.RawMessage) (any, error) {
			return contractPage(c.League("nacl").Fixtures(ctx, nil))
		},
		"getLeagueFixture": func(t *testing.T, c *Client, b json.RawMessage) (any, error) {
			return c.League("nacl").Fixture(ctx, id)
		},
		"getLeagueMatch":  func(t *testing.T, c *Client, b json.RawMessage) (any, error) { return c.League("nacl").Match(ctx, id) },
		"getLeagueConfig": func(t *testing.T, c *Client, b json.RawMessage) (any, error) { return c.League("nacl").Config(ctx) },
		"checkLeagueEligibility": func(t *testing.T, c *Client, b json.RawMessage) (any, error) {
			return c.League("nacl").CheckEligibility(ctx, contractBody[EligibilityRequest](t, b))
		},
		"getPlayerInventory": func(t *testing.T, c *Client, b json.RawMessage) (any, error) {
			return c.League("nacl").Inventory(ctx, credential, identifier, nil)
		},
		"getPlayersInventory": func(t *testing.T, c *Client, b json.RawMessage) (any, error) {
			return c.League("nacl").Inventories(ctx, credential, contractBody[InventoryBatchRequest](t, b))
		},
		"getLeagueItems": func(t *testing.T, c *Client, b json.RawMessage) (any, error) { return c.League("nacl").Items(ctx) },
		"submitCompleteMatch": func(t *testing.T, c *Client, b json.RawMessage) (any, error) {
			return c.Stats.SubmitMatch(ctx, contractBody[HeirMatchFile](t, b))
		},
		"listGamemodes":   func(t *testing.T, c *Client, b json.RawMessage) (any, error) { return c.Stats.Gamemodes(ctx) },
		"listStatSchemas": func(t *testing.T, c *Client, b json.RawMessage) (any, error) { return c.Stats.Schemas(ctx) },
		"beginMatch": func(t *testing.T, c *Client, b json.RawMessage) (any, error) {
			return c.Stats.BeginMatch(ctx, contractBody[BeginMatchRequest](t, b))
		},
		"appendUnits": func(t *testing.T, c *Client, b json.RawMessage) (any, error) {
			return c.Stats.AppendUnits(ctx, id, contractBody[AppendUnitsRequest](t, b))
		},
		"heartbeatMatch": func(t *testing.T, c *Client, b json.RawMessage) (any, error) { return c.Stats.Heartbeat(ctx, id) },
		"finalizeMatch":  func(t *testing.T, c *Client, b json.RawMessage) (any, error) { return c.Stats.Finalize(ctx, id) },
		"uploadMatch": func(t *testing.T, c *Client, b json.RawMessage) (any, error) {
			return c.Stats.Upload(ctx, contractBody[UploadMatchRequest](t, b))
		},
	}
	if len(fixtures.Cases) != len(calls) {
		t.Fatalf("fixtures=%d SDK operations=%d", len(fixtures.Cases), len(calls))
	}
	for _, fixture := range fixtures.Cases {
		t.Run(fixture.OperationID, func(t *testing.T) {
			invoke, ok := calls[fixture.OperationID]
			if !ok {
				t.Fatal("SDK operation is missing")
			}
			h := newHarness([]step{respond(200, string(fixture.ResponseBody))}, WithAPIKey("contract-key"))
			response, err := invoke(t, h.Client, fixture.RequestBody)
			if err != nil {
				t.Fatal(err)
			}
			if h.api.calls() != 1 {
				t.Fatalf("requests=%d", h.api.calls())
			}
			request := h.api.requests[0]
			if request.Method != fixture.Method || request.URL.RequestURI() != fixture.Path {
				t.Errorf("request=%s %s", request.Method, request.URL.RequestURI())
			}
			if request.Header.Get("Authorization") != "Bearer contract-key" {
				t.Error("missing authorization")
			}
			if len(fixture.RequestBody) > 0 {
				assertContractJSON(t, []byte(h.api.bodies[0]), fixture.RequestBody)
				if request.Header.Get("Content-Type") != "application/json" {
					t.Error("missing JSON content type")
				}
			} else if h.api.bodies[0] != "" {
				t.Error("GET sent a body")
			}
			if fixture.Method == "POST" && strings.HasPrefix(fixture.Path, statsBase) && fixture.OperationID != "submitCompleteMatch" && request.Header.Get("Idempotency-Key") == "" {
				t.Error("tracking request has no idempotency key")
			}
			encoded, err := json.Marshal(response)
			if err != nil {
				t.Fatal(err)
			}
			assertContractJSON(t, encoded, fixture.ResponseBody)
		})
	}
}

func contractBody[T any](t *testing.T, raw json.RawMessage) T {
	t.Helper()
	var body T
	if err := json.Unmarshal(raw, &body); err != nil {
		t.Fatal(err)
	}
	return body
}

func contractPage[I, B any](page *Page[I, B], err error) (any, error) {
	if err != nil {
		return nil, err
	}
	return page.Body, nil
}

func assertContractJSON(t *testing.T, actual, expected []byte) {
	t.Helper()
	var got, want any
	if err := json.Unmarshal(actual, &got); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(expected, &want); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(normalizeContractDates(got), normalizeContractDates(want)) {
		t.Errorf("JSON mismatch\ngot: %s\nwant: %s", actual, expected)
	}
}

// Go formats equivalent RFC3339 timestamps without redundant fractional zeros.
func normalizeContractDates(value any) any {
	switch v := value.(type) {
	case string:
		if date, err := time.Parse(time.RFC3339Nano, v); err == nil {
			return date.UTC().Format(time.RFC3339Nano)
		}
	case []any:
		for i := range v {
			v[i] = normalizeContractDates(v[i])
		}
	case map[string]any:
		for key, item := range v {
			v[key] = normalizeContractDates(item)
		}
	}
	return value
}
