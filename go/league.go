package heir

import (
	"context"
	"net/url"
	"strconv"
)

// Metric orders a leaderboard.
type Metric string

const (
	MetricMMR        Metric = "mmr"
	MetricHeirRating Metric = "heirRating"
	MetricWins       Metric = "wins"
	MetricLosses     Metric = "losses"
)

// FixtureStatus filters a League's fixtures.
type FixtureStatus string

const (
	FixtureScheduled FixtureStatus = "scheduled"
	FixturePlayed    FixtureStatus = "played"
	FixtureCancelled FixtureStatus = "cancelled"
)

// PlayerQuery scopes a player read. The zero value is the League's overall rating.
type PlayerQuery struct {
	Category Category
	Gamemode string
}

// RosterQuery scopes a Roster read.
type RosterQuery = PlayerQuery

// PlayerMatchesQuery scopes and pages a Player's rated match history.
type PlayerMatchesQuery struct {
	Category  Category
	Gamemode  string
	Page      int
	PageSize  int
	NextToken string
}

// RostersQuery scopes and pages a League's Rosters.
type RostersQuery = PlayerMatchesQuery

// LeaderboardQuery picks a leaderboard's metric and scope, and pages it.
type LeaderboardQuery struct {
	Metric    Metric
	Category  Category
	Gamemode  string
	Page      int
	PageSize  int
	NextToken string
}

// StandingsQuery pages the season standings.
type StandingsQuery struct {
	Page      int
	PageSize  int
	NextToken string
}

// FixturesQuery filters and pages a League's fixtures. The zero Status means scheduled.
type FixturesQuery struct {
	Status    FixtureStatus
	Page      int
	PageSize  int
	NextToken string
}

// InventoryQuery narrows an inventory read to one item key.
type InventoryQuery struct {
	Item string
}

// League is one League's public reads: players, ratings, Rosters, schedules, results and shop inventory. Reads need
// no key and are cached for a minute as the API asks; with the League's own developer key they draw on the plan's
// allowance instead of the per-address limit. Get one from Client.League.
type League struct {
	// Ref is the League as it was named: its vanity name or Discord server ID.
	Ref string

	client *Client
	base   string
}

// Player reads one current Member by linked game account, for nameplates and player cards. The answer's Player is
// nil for an unknown, unlinked, transferred or departed identity.
func (l *League) Player(ctx context.Context, credential, identifier string, query *PlayerQuery, options ...RequestOption) (*PlayerResponse, error) {
	return get[PlayerResponse](ctx, l, "/players/"+url.PathEscape(credential)+"/"+url.PathEscape(identifier), scopeValues(query), options)
}

// LookupPlayers reads up to 100 game accounts at once, each answered in order, including duplicates and unavailable identities.
func (l *League) LookupPlayers(ctx context.Context, request PlayerLookupRequest, options ...RequestOption) (*PlayerLookupResponse, error) {
	return post[PlayerLookupResponse](ctx, l, "/players/lookup", request, options)
}

// PlayerStats reads the Player's League win/loss record and stored performance totals for the scope.
func (l *League) PlayerStats(ctx context.Context, credential, identifier string, query *PlayerQuery, options ...RequestOption) (*PlayerStatsResponse, error) {
	return get[PlayerStatsResponse](ctx, l, "/players/"+url.PathEscape(credential)+"/"+url.PathEscape(identifier)+"/stats", scopeValues(query), options)
}

// PlayerMatches reads the Player's rated results and MMR changes, newest first.
func (l *League) PlayerMatches(ctx context.Context, credential, identifier string, query *PlayerMatchesQuery, options ...RequestOption) (*Page[PlayerMatch, *PlayerMatchesResponse], error) {
	q := valueOf(query)
	body, err := get[PlayerMatchesResponse](ctx, l, "/players/"+url.PathEscape(credential)+"/"+url.PathEscape(identifier)+"/matches", listValues(q.Category, q.Gamemode, q.Page, q.PageSize, q.NextToken), options)
	if err != nil {
		return nil, err
	}
	return newPage(body, body.Matches, body.HasMore, body.NextToken, func(ctx context.Context, token string) (*Page[PlayerMatch, *PlayerMatchesResponse], error) {
		return l.PlayerMatches(ctx, credential, identifier, &PlayerMatchesQuery{Category: q.Category, Gamemode: q.Gamemode, PageSize: q.PageSize, NextToken: token}, options...)
	}), nil
}

// Rosters reads the active Rosters with their Team tags, logos, captain and Team MMR.
func (l *League) Rosters(ctx context.Context, query *RostersQuery, options ...RequestOption) (*Page[Roster, *RostersResponse], error) {
	q := valueOf(query)
	body, err := get[RostersResponse](ctx, l, "/rosters", listValues(q.Category, q.Gamemode, q.Page, q.PageSize, q.NextToken), options)
	if err != nil {
		return nil, err
	}
	return newPage(body, body.Rosters, body.HasMore, body.NextToken, func(ctx context.Context, token string) (*Page[Roster, *RostersResponse], error) {
		return l.Rosters(ctx, &RostersQuery{Category: q.Category, Gamemode: q.Gamemode, PageSize: q.PageSize, NextToken: token}, options...)
	}), nil
}

// Roster reads one active Roster and its seated Members.
func (l *League) Roster(ctx context.Context, id string, query *RosterQuery, options ...RequestOption) (*RosterResponse, error) {
	return get[RosterResponse](ctx, l, "/rosters/"+url.PathEscape(id), scopeValues(query), options)
}

// Leaderboard reads current Members ordered by MMR, Heir Rating, wins or losses. It is a five-minute snapshot;
// the Body's SnapshotAt says which.
func (l *League) Leaderboard(ctx context.Context, query *LeaderboardQuery, options ...RequestOption) (*Page[LeaderboardEntry, *LeaderboardResponse], error) {
	q := valueOf(query)
	values := listValues(q.Category, q.Gamemode, q.Page, q.PageSize, q.NextToken)
	if q.Metric != "" {
		values.Set("metric", string(q.Metric))
	}
	body, err := get[LeaderboardResponse](ctx, l, "/leaderboards", values, options)
	if err != nil {
		return nil, err
	}
	return newPage(body, body.Entries, body.HasMore, body.NextToken, func(ctx context.Context, token string) (*Page[LeaderboardEntry, *LeaderboardResponse], error) {
		return l.Leaderboard(ctx, &LeaderboardQuery{Metric: q.Metric, Category: q.Category, Gamemode: q.Gamemode, PageSize: q.PageSize, NextToken: token}, options...)
	}), nil
}

// Standings reads the current-season Roster standings in competition order.
func (l *League) Standings(ctx context.Context, query *StandingsQuery, options ...RequestOption) (*Page[Standing, *StandingsResponse], error) {
	q := valueOf(query)
	body, err := get[StandingsResponse](ctx, l, "/standings", listValues("", "", q.Page, q.PageSize, q.NextToken), options)
	if err != nil {
		return nil, err
	}
	return newPage(body, body.Standings, body.HasMore, body.NextToken, func(ctx context.Context, token string) (*Page[Standing, *StandingsResponse], error) {
		return l.Standings(ctx, &StandingsQuery{PageSize: q.PageSize, NextToken: token}, options...)
	}), nil
}

// Fixtures reads fixtures in scheduled-time order: scheduled by default, or played or cancelled by Status.
func (l *League) Fixtures(ctx context.Context, query *FixturesQuery, options ...RequestOption) (*Page[Fixture, *FixturesResponse], error) {
	q := valueOf(query)
	values := listValues("", "", q.Page, q.PageSize, q.NextToken)
	if q.Status != "" {
		values.Set("status", string(q.Status))
	}
	body, err := get[FixturesResponse](ctx, l, "/fixtures", values, options)
	if err != nil {
		return nil, err
	}
	return newPage(body, body.Fixtures, body.HasMore, body.NextToken, func(ctx context.Context, token string) (*Page[Fixture, *FixturesResponse], error) {
		return l.Fixtures(ctx, &FixturesQuery{Status: q.Status, PageSize: q.PageSize, NextToken: token}, options...)
	}), nil
}

// Fixture reads one fixture: its Rosters, time, status, stream link and recorded result.
func (l *League) Fixture(ctx context.Context, id string, options ...RequestOption) (*FixtureResponse, error) {
	return get[FixtureResponse](ctx, l, "/fixtures/"+url.PathEscape(id), nil, options)
}

// Match reads an official result or approved recording by UUID.
func (l *League) Match(ctx context.Context, id string, options ...RequestOption) (*MatchResponse, error) {
	return get[MatchResponse](ctx, l, "/matches/"+url.PathEscape(id), nil, options)
}

// Config reads the League's game credentials, active gamemodes, rating categories, rank definitions and batch limits.
func (l *League) Config(ctx context.Context, options ...RequestOption) (*LeagueConfigResponse, error) {
	return get[LeagueConfigResponse](ctx, l, "/config", nil, options)
}

// CheckEligibility checks up to 100 game accounts against a fixture and one of its Rosters. It requires the League's
// developer key with the gamemode granted, and is advisory: it reserves no seats. Call it from your server.
func (l *League) CheckEligibility(ctx context.Context, request EligibilityRequest, options ...RequestOption) (*EligibilityResponse, error) {
	return post[EligibilityResponse](ctx, l, "/eligibility/check", request, options)
}

// Inventory reads the items one game account's owner holds in the League's shop right now. An empty list is a normal answer.
func (l *League) Inventory(ctx context.Context, credential, identifier string, query *InventoryQuery, options ...RequestOption) (*InventoryResponse, error) {
	values := url.Values{}
	if query != nil && query.Item != "" {
		values.Set("item", query.Item)
	}
	return get[InventoryResponse](ctx, l, "/inventory/"+url.PathEscape(credential)+"/"+url.PathEscape(identifier), values, options)
}

// Inventories reads the same for up to 100 game accounts at once, such as everyone on a server. It is not cached.
func (l *League) Inventories(ctx context.Context, credential string, request InventoryBatchRequest, options ...RequestOption) (*InventoryBatchResponse, error) {
	return post[InventoryBatchResponse](ctx, l, "/inventory/"+url.PathEscape(credential), request, options)
}

// Items reads every item the League's shop knows, and the kinds of game account its inventory calls accept.
func (l *League) Items(ctx context.Context, options ...RequestOption) (*LeagueItemsResponse, error) {
	return get[LeagueItemsResponse](ctx, l, "/items", nil, options)
}

func get[T any](ctx context.Context, l *League, path string, query url.Values, options []RequestOption) (*T, error) {
	var out T
	if err := l.client.do(ctx, call{method: "GET", path: l.base + path, query: query, idempotent: true, cacheable: true}, &out, options...); err != nil {
		return nil, err
	}
	return &out, nil
}

// post sends the reads that take a body. They read and never write, so they are safe to send again; the API does not cache them.
func post[T any](ctx context.Context, l *League, path string, body any, options []RequestOption) (*T, error) {
	var out T
	if err := l.client.do(ctx, call{method: "POST", path: l.base + path, body: body, idempotent: true, cacheable: false}, &out, options...); err != nil {
		return nil, err
	}
	return &out, nil
}

func valueOf[T any](query *T) T {
	if query == nil {
		var zero T
		return zero
	}
	return *query
}

func scopeValues(query *PlayerQuery) url.Values {
	q := valueOf(query)
	return listValues(q.Category, q.Gamemode, 0, 0, "")
}

// listValues encodes the parameters every list shares; zero values are left out, so the API applies its defaults.
func listValues(category Category, gamemode string, page, pageSize int, nextToken string) url.Values {
	values := url.Values{}
	if category != "" {
		values.Set("category", string(category))
	}
	if gamemode != "" {
		values.Set("gamemode", gamemode)
	}
	if nextToken != "" {
		values.Set("nextToken", nextToken)
	} else if page > 0 {
		values.Set("page", strconv.Itoa(page))
	}
	if pageSize > 0 {
		values.Set("pageSize", strconv.Itoa(pageSize))
	}
	return values
}
