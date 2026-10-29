package heir

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"net/url"
)

const statsBase = "/public/v1/stats"

// Stats is stat submission: send your game's stats to a League, for any gamemode it plays. Every call needs an API
// key with the gamemode granted. It is available while the League's stat submission API is switched on; otherwise
// the API answers 503 `not-available`.
type Stats struct {
	client *Client
}

// Gamemodes lists the gamemodes this key may submit, built-in and custom, each with the stat keys a Player line may
// carry and an empty heir-match-v1 document to fill in.
func (s *Stats) Gamemodes(ctx context.Context, options ...RequestOption) (*GamemodeCatalog, error) {
	var out GamemodeCatalog
	if err := s.client.do(ctx, call{method: "GET", path: statsBase + "/gamemodes", idempotent: true}, &out, options...); err != nil {
		return nil, err
	}
	return &out, nil
}

// Schemas lists the gamemode schemas this key may track a match under, with every counter and what one unit is, and the key's allowances.
func (s *Stats) Schemas(ctx context.Context, options ...RequestOption) (*StatSchemaCatalog, error) {
	var out StatSchemaCatalog
	if err := s.client.do(ctx, call{method: "GET", path: statsBase + "/schemas", idempotent: true}, &out, options...); err != nil {
		return nil, err
	}
	return &out, nil
}

// SubmitMatch sends one finished match as a heir-match-v1 document, for any gamemode. Set Reference to your own id
// for the match: a repeat with the same contents is a no-op, and the client may then safely send it again after a
// connection failure. Timestamps may carry at most millisecond precision; truncate a time.Now() before sending it.
func (s *Stats) SubmitMatch(ctx context.Context, file HeirMatchFile, options ...RequestOption) (*MatchEntryReceipt, error) {
	var out MatchEntryReceipt
	err := s.client.do(ctx, call{method: "POST", path: statsBase + "/matches/complete", body: file, idempotent: file.Reference != nil}, &out, options...)
	if err != nil {
		return nil, err
	}
	return &out, nil
}

// BeginMatch opens a live match. It takes one of the League's live sessions until finalized or silent for 30
// minutes. Beginning it again returns it and takes nothing more.
func (s *Stats) BeginMatch(ctx context.Context, request BeginMatchRequest, options ...RequestOption) (*BeginMatchResponse, error) {
	return write[BeginMatchResponse](ctx, s, statsBase+"/matches", request, options)
}

// AppendUnits adds rounds (or a whole game, for a gamemode without rounds) to an open match. The request is
// accepted or refused whole.
func (s *Stats) AppendUnits(ctx context.Context, matchID string, request AppendUnitsRequest, options ...RequestOption) (*AppendUnitsResponse, error) {
	return write[AppendUnitsResponse](ctx, s, statsBase+"/matches/"+url.PathEscape(matchID)+"/units", request, options)
}

// Heartbeat says the match is still being played when no unit is ready; a match silent for 30 minutes is closed and held for review.
func (s *Stats) Heartbeat(ctx context.Context, matchID string, options ...RequestOption) (*HeartbeatMatchResponse, error) {
	return write[HeartbeatMatchResponse](ctx, s, statsBase+"/matches/"+url.PathEscape(matchID)+"/heartbeat", struct{}{}, options)
}

// Finalize closes the match and frees its live session. A game without its result, or a missing round, holds it for an Organizer's review.
func (s *Stats) Finalize(ctx context.Context, matchID string, options ...RequestOption) (*FinalizeMatchResponse, error) {
	return write[FinalizeMatchResponse](ctx, s, statsBase+"/matches/"+url.PathEscape(matchID)+"/finalize", struct{}{}, options)
}

// Upload sends a complete tracked match in one request. It never holds a live session; the same upload again changes nothing.
func (s *Stats) Upload(ctx context.Context, request UploadMatchRequest, options ...RequestOption) (*UploadMatchResponse, error) {
	return write[UploadMatchResponse](ctx, s, statsBase+"/uploads", request, options)
}

// write sends a tracking write with an Idempotency-Key, generated unless WithIdempotencyKey gave one, so a retry never writes twice.
func write[T any](ctx context.Context, s *Stats, path string, body any, options []RequestOption) (*T, error) {
	var opts requestOptions
	for _, option := range options {
		option(&opts)
	}
	if opts.idempotencyKey == "" {
		options = append([]RequestOption{WithIdempotencyKey(NewIdempotencyKey())}, options...)
	}
	var out T
	if err := s.client.do(ctx, call{method: "POST", path: path, body: body, idempotent: true}, &out, options...); err != nil {
		return nil, err
	}
	return &out, nil
}

// NewIdempotencyKey makes a fresh idempotency key: a version 4 UUID.
func NewIdempotencyKey() string {
	var b [16]byte
	if _, err := rand.Read(b[:]); err != nil {
		panic("heir: crypto/rand failed: " + err.Error())
	}
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	s := hex.EncodeToString(b[:])
	return s[:8] + "-" + s[8:12] + "-" + s[12:16] + "-" + s[16:20] + "-" + s[20:]
}
