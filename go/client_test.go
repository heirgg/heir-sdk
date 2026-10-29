package heir

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"regexp"
	"strings"
	"testing"
	"time"
)

// step answers one request of a fake API.
type step func(*http.Request) (*http.Response, error)

// fakeAPI answers each request with the next step and keeps every request for inspection.
type fakeAPI struct {
	steps    []step
	requests []*http.Request
	bodies   []string
}

func (f *fakeAPI) RoundTrip(request *http.Request) (*http.Response, error) {
	body := ""
	if request.Body != nil {
		raw, _ := io.ReadAll(request.Body)
		body = string(raw)
	}
	f.requests = append(f.requests, request)
	f.bodies = append(f.bodies, body)
	if len(f.steps) == 0 {
		return nil, fmt.Errorf("unexpected request %s %s", request.Method, request.URL)
	}
	next := f.steps[0]
	f.steps = f.steps[1:]
	return next(request)
}

func (f *fakeAPI) calls() int { return len(f.requests) }

func respond(status int, body string, header ...string) step {
	return func(request *http.Request) (*http.Response, error) {
		h := http.Header{"Content-Type": {"application/json"}}
		for i := 0; i+1 < len(header); i += 2 {
			h.Set(header[i], header[i+1])
		}
		return &http.Response{StatusCode: status, Header: h, Body: io.NopCloser(strings.NewReader(body)), Request: request}, nil
	}
}

func apiError(status int, code, message string, header ...string) step {
	return respond(status, fmt.Sprintf(`{"error":%q,"message":%q}`, code, message), header...)
}

func broken(request *http.Request) (*http.Response, error) {
	return nil, errors.New("connection reset")
}

// harness is a client over a fake API whose sleeps are recorded instead of taken, and whose clock is a variable.
type harness struct {
	*Client
	api    *fakeAPI
	sleeps []time.Duration
	clock  time.Time
}

func newHarness(steps []step, options ...Option) *harness {
	h := &harness{api: &fakeAPI{steps: steps}, clock: time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC)}
	h.Client = NewClient(append([]Option{WithHTTPClient(&http.Client{Transport: h.api})}, options...)...)
	h.Client.sleep = func(ctx context.Context, d time.Duration) error { h.sleeps = append(h.sleeps, d); return nil }
	h.Client.now = func() time.Time { return h.clock }
	return h
}

const player = `{"player":{"identifier":"A1B2C3D4E5F67890","displayName":"Ada","profileUrl":null,"mmr":null,"rank":null,"heirRating":null,"roster":null}}`

func TestRequestBuildsURLAndHeaders(t *testing.T) {
	h := newHarness([]step{respond(200, player)}, WithAPIKey("key-1"), WithUserAgent("my-server/2.0"))
	answer, err := h.League("nacl").Player(context.Background(), "mordhau", "A1B2C3D4E5F67890", &PlayerQuery{Category: CategoryCompetitive})
	if err != nil {
		t.Fatal(err)
	}
	if answer.Player == nil || answer.Player.DisplayName != "Ada" {
		t.Fatalf("answer = %+v", answer)
	}
	request := h.api.requests[0]
	if got := request.URL.String(); got != "https://api.heir.gg/public/v1/leagues/nacl/players/mordhau/A1B2C3D4E5F67890?category=competitive" {
		t.Errorf("url = %s", got)
	}
	for name, want := range map[string]string{"Authorization": "Bearer key-1", "Accept": "application/json", "User-Agent": "heir-sdk-go/" + Version + " my-server/2.0"} {
		if got := request.Header.Get(name); got != want {
			t.Errorf("%s = %q, want %q", name, got, want)
		}
	}
	if !h.Authenticated() {
		t.Error("Authenticated() = false")
	}
}

func TestKeylessReadsAndEscaping(t *testing.T) {
	h := newHarness([]step{respond(200, `{"fixture":{}}`)}, WithBaseURL("https://staging.example.test/"))
	if _, err := h.League("123456789012345678").Fixture(context.Background(), "a/b c"); err != nil {
		t.Fatal(err)
	}
	request := h.api.requests[0]
	if got := request.URL.String(); got != "https://staging.example.test/public/v1/leagues/123456789012345678/fixtures/a%2Fb%20c" {
		t.Errorf("url = %s", got)
	}
	if request.Header.Get("Authorization") != "" || h.Authenticated() {
		t.Error("a key was sent without one being given")
	}
}

func TestPostsJSONForLookupReads(t *testing.T) {
	h := newHarness([]step{respond(200, `{"players":[]}`)})
	_, err := h.League("nacl").LookupPlayers(context.Background(), PlayerLookupRequest{Credential: "steam", Identifiers: []string{"76561198000000000"}})
	if err != nil {
		t.Fatal(err)
	}
	request := h.api.requests[0]
	if request.Method != "POST" || request.Header.Get("Content-Type") != "application/json" {
		t.Errorf("method %s content-type %q", request.Method, request.Header.Get("Content-Type"))
	}
	var sent map[string]any
	if err := json.Unmarshal([]byte(h.api.bodies[0]), &sent); err != nil || sent["credential"] != "steam" {
		t.Errorf("body = %s", h.api.bodies[0])
	}
	if _, hasCategory := sent["category"]; hasCategory {
		t.Errorf("an empty category was sent: %s", h.api.bodies[0])
	}
}

func TestAPIErrorEnvelope(t *testing.T) {
	h := newHarness([]step{respond(400, `{"error":"invalid-request","message":"The match could not be read.","issues":[{"path":"maps.0.winner","message":"Invalid option"}]}`)}, WithAPIKey("k"))
	_, err := h.Stats.SubmitMatch(context.Background(), HeirMatchFile{Format: HeirMatchFormatHeirMatchV1, StartedAt: time.Now()})
	var apiErr *APIError
	if !errors.As(err, &apiErr) {
		t.Fatalf("err = %v", err)
	}
	if apiErr.StatusCode != 400 || apiErr.Code != "invalid-request" || apiErr.Message != "The match could not be read." || len(apiErr.Issues) != 1 || apiErr.Issues[0].Path != "maps.0.winner" {
		t.Errorf("apiErr = %+v", apiErr)
	}
	if apiErr.IsRateLimited() || h.api.calls() != 1 || !strings.Contains(apiErr.Error(), "invalid-request") {
		t.Errorf("rateLimited=%v calls=%d text=%q", apiErr.IsRateLimited(), h.api.calls(), apiErr.Error())
	}
}

func TestAnswerThatIsNotTheEnvelopeIsStillAnAPIError(t *testing.T) {
	gateway := respond(502, "<html>bad gateway</html>")
	h := newHarness([]step{gateway, gateway, gateway})
	_, err := h.League("nacl").Config(context.Background())
	var apiErr *APIError
	if !errors.As(err, &apiErr) || apiErr.StatusCode != 502 || apiErr.Code != "unknown" || string(apiErr.Body) != "<html>bad gateway</html>" {
		t.Fatalf("err = %v", err)
	}
	if h.api.calls() != 3 || len(h.sleeps) != 2 {
		t.Errorf("calls=%d sleeps=%v: a gateway error on a read is retried maxRetries times", h.api.calls(), h.sleeps)
	}
}

func TestConnectionFailureIsRetriedForARead(t *testing.T) {
	h := newHarness([]step{broken, respond(200, `{"items":[],"credentials":[]}`)})
	if _, err := h.League("nacl").Items(context.Background()); err != nil {
		t.Fatal(err)
	}
	if h.api.calls() != 2 {
		t.Errorf("calls = %d", h.api.calls())
	}
}

func TestConnectionFailureIsNotRetriedForASubmissionWithoutReference(t *testing.T) {
	h := newHarness([]step{broken}, WithAPIKey("k"))
	_, err := h.Stats.SubmitMatch(context.Background(), HeirMatchFile{Format: HeirMatchFormatHeirMatchV1, StartedAt: time.Now()})
	var connErr *ConnectionError
	if !errors.As(err, &connErr) || connErr.Timeout || connErr.Unwrap() == nil || !strings.Contains(connErr.Error(), "could not reach") {
		t.Fatalf("err = %v", err)
	}
	if h.api.calls() != 1 {
		t.Errorf("calls = %d", h.api.calls())
	}
}

func TestTimeoutOfOneAttempt(t *testing.T) {
	hang := func(request *http.Request) (*http.Response, error) {
		<-request.Context().Done()
		return nil, request.Context().Err()
	}
	h := newHarness([]step{hang, hang, hang}, WithTimeout(20*time.Millisecond))
	_, err := h.League("nacl").Config(context.Background())
	var connErr *ConnectionError
	if !errors.As(err, &connErr) || !connErr.Timeout {
		t.Fatalf("err = %v", err)
	}
	if h.api.calls() != 1 {
		t.Errorf("calls = %d: a timed-out attempt is not retried", h.api.calls())
	}
}

func TestCallerCancellationIsReturnedAsItIs(t *testing.T) {
	hang := func(request *http.Request) (*http.Response, error) {
		<-request.Context().Done()
		return nil, request.Context().Err()
	}
	h := newHarness([]step{hang})
	ctx, cancel := context.WithCancel(context.Background())
	go func() { time.Sleep(10 * time.Millisecond); cancel() }()
	_, err := h.League("nacl").Config(ctx)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("err = %v", err)
	}
}

func TestRetryAfterIsWaitedFor(t *testing.T) {
	h := newHarness([]step{apiError(429, "rate-limited", "Slow down.", "Retry-After", "2"), respond(200, player)})
	if _, err := h.League("nacl").Player(context.Background(), "mordhau", "A1B2C3D4E5F67890", nil); err != nil {
		t.Fatal(err)
	}
	if h.api.calls() != 2 || len(h.sleeps) != 1 || h.sleeps[0] != 2*time.Second {
		t.Errorf("calls=%d sleeps=%v", h.api.calls(), h.sleeps)
	}
}

func TestRetryAfterBeyondTheLimitFailsAtOnce(t *testing.T) {
	h := newHarness([]step{apiError(429, "rate-limited", "Try again in a minute.", "Retry-After", "60")}, WithMaxRetryDelay(30*time.Second))
	_, err := h.League("nacl").Config(context.Background())
	var apiErr *APIError
	if !errors.As(err, &apiErr) || !apiErr.IsRateLimited() || apiErr.RetryAfter != 60*time.Second {
		t.Fatalf("err = %v", err)
	}
	if h.api.calls() != 1 || len(h.sleeps) != 0 {
		t.Errorf("calls=%d sleeps=%v", h.api.calls(), h.sleeps)
	}
}

func TestRetriesStopAtMaxAndSkipOtherClientErrors(t *testing.T) {
	down := apiError(503, "unavailable", "Later.")
	h := newHarness([]step{down, down, down, down}, WithMaxRetries(2))
	_, err := h.League("nacl").Config(context.Background())
	var apiErr *APIError
	if !errors.As(err, &apiErr) || apiErr.StatusCode != 503 || h.api.calls() != 3 {
		t.Fatalf("err=%v calls=%d", err, h.api.calls())
	}
	once := newHarness([]step{apiError(404, "league-not-found", "No.")})
	_, err = once.League("nope").Config(context.Background())
	if !errors.As(err, &apiErr) || apiErr.Code != "league-not-found" || once.api.calls() != 1 {
		t.Fatalf("err=%v calls=%d", err, once.api.calls())
	}
}

func TestCacheServesFreshAnswersThenRevalidates(t *testing.T) {
	h := newHarness([]step{
		respond(200, `{"items":[{"key":"gold","name":"Gold","expiresAt":null,"edition":null,"imageUrl":null}]}`, "ETag", `"v1"`, "Cache-Control", "public, max-age=60"),
		func(request *http.Request) (*http.Response, error) {
			if request.Header.Get("If-None-Match") != `"v1"` {
				t.Errorf("If-None-Match = %q", request.Header.Get("If-None-Match"))
			}
			return respond(304, "", "Cache-Control", "public, max-age=60")(request)
		},
		respond(200, `{"items":[]}`, "ETag", `"v2"`, "Cache-Control", "public, max-age=60"),
	})
	league := h.League("nacl")
	read := func() int {
		answer, err := league.Inventory(context.Background(), "mordhau", "A1B2C3D4E5F67890", nil)
		if err != nil {
			t.Fatal(err)
		}
		return len(answer.Items)
	}
	if read() != 1 || read() != 1 || h.api.calls() != 1 {
		t.Fatalf("a fresh answer was not served from memory: calls=%d", h.api.calls())
	}
	h.clock = h.clock.Add(61 * time.Second)
	if read() != 1 || h.api.calls() != 2 {
		t.Fatalf("a stale answer was not revalidated: calls=%d", h.api.calls())
	}
	if read() != 1 || h.api.calls() != 2 {
		t.Fatalf("a 304 did not make the answer fresh again: calls=%d", h.api.calls())
	}
	h.ClearCache()
	if read() != 0 || h.api.calls() != 3 {
		t.Fatalf("ClearCache did not forget: calls=%d", h.api.calls())
	}
}

func TestCacheSkipsNoStoreAndRespectsOptOuts(t *testing.T) {
	page := `{"rosters":[],"page":0,"pageSize":25,"hasMore":false,"nextToken":null}`
	h := newHarness([]step{respond(200, page, "Cache-Control", "no-store", "ETag", `"x"`), respond(200, page, "Cache-Control", "no-store", "ETag", `"x"`)})
	for range 2 {
		if _, err := h.League("nacl").Rosters(context.Background(), nil); err != nil {
			t.Fatal(err)
		}
	}
	if h.api.calls() != 2 {
		t.Errorf("a no-store answer was cached")
	}
	fresh := respond(200, `{"items":[],"credentials":[]}`, "Cache-Control", "max-age=60")
	off := newHarness([]step{fresh, fresh}, WithoutCache())
	for range 2 {
		if _, err := off.League("nacl").Items(context.Background()); err != nil {
			t.Fatal(err)
		}
	}
	if off.api.calls() != 2 {
		t.Errorf("WithoutCache still cached")
	}
	perCall := newHarness([]step{fresh, fresh})
	for range 2 {
		if _, err := perCall.League("nacl").Items(context.Background(), NoCache()); err != nil {
			t.Fatal(err)
		}
	}
	if perCall.api.calls() != 2 {
		t.Errorf("NoCache() still cached")
	}
}

func TestCacheKeepsKeyedAndKeylessAnswersApart(t *testing.T) {
	api := &fakeAPI{steps: []step{respond(200, `{"items":[{"key":"a","name":"","description":"","lasts":"permanent","imageUrl":null}],"credentials":[]}`, "Cache-Control", "max-age=60"), respond(200, `{"items":[],"credentials":[]}`, "Cache-Control", "max-age=60")}}
	anon := NewClient(WithHTTPClient(&http.Client{Transport: api}))
	keyed := NewClient(WithHTTPClient(&http.Client{Transport: api}), WithAPIKey("k"))
	first, _ := anon.League("nacl").Items(context.Background())
	second, _ := keyed.League("nacl").Items(context.Background())
	if first == nil || second == nil || len(first.Items) != 1 || len(second.Items) != 0 {
		t.Fatalf("first=%+v second=%+v", first, second)
	}
}

func roster(name string) string {
	return fmt.Sprintf(`{"id":%q,"name":%q,"tag":null,"logoUrl":null,"teamMmr":1500,"provisional":false,"category":"competitive","captain":null}`, name, name)
}

func TestPaginationWalksEveryPageWithTheSameFilters(t *testing.T) {
	h := newHarness([]step{
		respond(200, `{"rosters":[`+roster("a")+`,`+roster("b")+`],"page":0,"pageSize":2,"hasMore":true,"nextToken":"t1"}`),
		respond(200, `{"rosters":[`+roster("c")+`],"page":1,"pageSize":2,"hasMore":true,"nextToken":"t2"}`),
		respond(200, `{"rosters":[],"page":2,"pageSize":2,"hasMore":false,"nextToken":null}`),
	})
	ctx := context.Background()
	first, err := h.League("nacl").Rosters(ctx, &RostersQuery{Category: CategoryCompetitive, PageSize: 2})
	if err != nil {
		t.Fatal(err)
	}
	if len(first.Items) != 2 || !first.HasMore() || first.NextToken() != "t1" || first.Body.Page != 0 {
		t.Fatalf("first = %+v", first)
	}
	var names []string
	for item, err := range first.All(ctx) {
		if err != nil {
			t.Fatal(err)
		}
		names = append(names, item.Name)
	}
	if strings.Join(names, ",") != "a,b,c" {
		t.Errorf("names = %v", names)
	}
	var queries []string
	for _, request := range h.api.requests {
		queries = append(queries, request.URL.RawQuery)
	}
	if want := []string{"category=competitive&pageSize=2", "category=competitive&nextToken=t1&pageSize=2", "category=competitive&nextToken=t2&pageSize=2"}; strings.Join(queries, " ") != strings.Join(want, " ") {
		t.Errorf("queries = %v", queries)
	}
	// Walking by hand: Next fetches again, so the fake API gets the two later pages back.
	h.api.steps = []step{
		respond(200, `{"rosters":[`+roster("c")+`],"page":1,"pageSize":2,"hasMore":true,"nextToken":"t2"}`),
		respond(200, `{"rosters":[],"page":2,"pageSize":2,"hasMore":false,"nextToken":null}`),
	}
	second, err := first.Next(ctx)
	if err != nil || second == nil || len(second.Items) != 1 {
		t.Fatalf("second=%+v err=%v", second, err)
	}
	last, err := second.Next(ctx)
	if err != nil || last == nil || last.HasMore() {
		t.Fatalf("last=%+v err=%v", last, err)
	}
	if end, err := last.Next(ctx); end != nil || err != nil {
		t.Errorf("after the last page: %+v %v", end, err)
	}
}

func TestLeaderboardBodyCarriesTheSnapshot(t *testing.T) {
	h := newHarness([]step{respond(200, `{"metric":"mmr","category":"overall","entries":[{"position":1,"displayName":"Ada","profileUrl":null,"value":1800,"provisional":false}],"page":0,"pageSize":25,"hasMore":false,"nextToken":null,"snapshotAt":"2026-10-29T10:00:00.000Z","snapshotExpiresAt":"2026-10-29T10:05:00.000Z"}`)})
	page, err := h.League("nacl").Leaderboard(context.Background(), &LeaderboardQuery{Metric: MetricMMR})
	if err != nil {
		t.Fatal(err)
	}
	if page.Items[0].DisplayName != "Ada" || page.Body.SnapshotAt.Hour() != 10 || h.api.requests[0].URL.RawQuery != "metric=mmr" {
		t.Errorf("page=%+v query=%s", page, h.api.requests[0].URL.RawQuery)
	}
}

var uuidPattern = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`)

func TestTrackingWritesCarryIdempotencyKeysAndDryRun(t *testing.T) {
	h := newHarness([]step{
		respond(200, `{"matchId":"m1","created":true,"approval":"automatic","replayed":false}`),
		respond(200, `{"accepted":1,"duplicates":0,"dryRun":true}`),
		respond(200, `{"closed":true,"status":"approved","heldForReview":false,"replayed":false}`),
	}, WithAPIKey("k"))
	ctx := context.Background()
	begun, err := h.Stats.BeginMatch(ctx, BeginMatchRequest{MatchID: "m1", StartedAt: 1790000000000})
	if err != nil || begun.Approval != ApprovalAutomatic {
		t.Fatalf("begun=%+v err=%v", begun, err)
	}
	appended, err := h.Stats.AppendUnits(ctx, "m1", AppendUnitsRequest{Games: []GameSubmission{{SchemaRef: "mordhau.skirmish@1", GameID: "g1"}}}, WithIdempotencyKey("g1-round-0"), DryRun())
	if err != nil || appended.DryRun == nil || !*appended.DryRun {
		t.Fatalf("appended=%+v err=%v", appended, err)
	}
	if _, err := h.Stats.Finalize(ctx, "m1"); err != nil {
		t.Fatal(err)
	}
	begin, appendReq, finalize := h.api.requests[0], h.api.requests[1], h.api.requests[2]
	if !uuidPattern.MatchString(begin.Header.Get("Idempotency-Key")) {
		t.Errorf("generated key = %q", begin.Header.Get("Idempotency-Key"))
	}
	if appendReq.Header.Get("Idempotency-Key") != "g1-round-0" || appendReq.URL.String() != "https://api.heir.gg/public/v1/stats/matches/m1/units?dryRun=true" {
		t.Errorf("append: key=%q url=%s", appendReq.Header.Get("Idempotency-Key"), appendReq.URL)
	}
	if finalize.URL.Path != "/public/v1/stats/matches/m1/finalize" || h.api.bodies[2] != "{}" || finalize.Header.Get("Content-Type") != "application/json" {
		t.Errorf("finalize: url=%s body=%q", finalize.URL, h.api.bodies[2])
	}
}

func TestTrackingWriteRetriesWithTheSameKey(t *testing.T) {
	h := newHarness([]step{broken, respond(200, `{"deadline":1,"replayed":false}`)}, WithAPIKey("k"))
	if _, err := h.Stats.Heartbeat(context.Background(), "m1"); err != nil {
		t.Fatal(err)
	}
	first, second := h.api.requests[0].Header.Get("Idempotency-Key"), h.api.requests[1].Header.Get("Idempotency-Key")
	if first == "" || first != second {
		t.Errorf("keys differ across the retry: %q %q", first, second)
	}
}

func TestSubmissionWithAReferenceIsRetried(t *testing.T) {
	h := newHarness([]step{broken, respond(200, `{"kind":"match","id":"9f6d2a70-0000-4000-8000-000000000000","status":"approved","created":true,"replayed":false,"problems":[]}`)}, WithAPIKey("k"))
	reference, identity, side := "lobby-42", "A1B2C3D4E5F67890", "a"
	receipt, err := h.Stats.SubmitMatch(context.Background(), HeirMatchFile{Format: HeirMatchFormatHeirMatchV1, Reference: &reference, StartedAt: time.Date(2026, 10, 16, 19, 0, 0, 0, time.UTC),
		Maps: []HeirMatchMap{{Players: []HeirMatchPlayer{{Identity: &identity, Side: &side}}}}})
	if err != nil || !receipt.Created || receipt.Status != ReceiptStatusApproved || h.api.calls() != 2 {
		t.Fatalf("receipt=%+v err=%v calls=%d", receipt, err, h.api.calls())
	}
	var sent map[string]any
	_ = json.Unmarshal([]byte(h.api.bodies[1]), &sent)
	if sent["startedAt"] != "2026-10-16T19:00:00Z" || sent["reference"] != "lobby-42" {
		t.Errorf("body = %s", h.api.bodies[1])
	}
}

func TestNewIdempotencyKeyIsAUUID(t *testing.T) {
	a, b := NewIdempotencyKey(), NewIdempotencyKey()
	if !uuidPattern.MatchString(a) || a == b {
		t.Errorf("keys = %s %s", a, b)
	}
}

func TestParseRetryAfter(t *testing.T) {
	if parseRetryAfter("") != 0 || parseRetryAfter("2") != 2*time.Second || parseRetryAfter("-1") != 0 {
		t.Error("seconds form")
	}
	if got := parseRetryAfter(time.Now().Add(90 * time.Second).UTC().Format(http.TimeFormat)); got < 88*time.Second || got > 91*time.Second {
		t.Errorf("date form = %v", got)
	}
}

// The hand-written query enums must say what the API document says.
func TestQueryEnumsMatchTheSpec(t *testing.T) {
	raw, err := os.ReadFile("../spec/public-openapi.json")
	if err != nil {
		t.Skip("spec not available:", err)
	}
	var doc struct {
		Paths map[string]map[string]struct {
			Parameters []struct {
				Name   string `json:"name"`
				Schema struct {
					Enum []string `json:"enum"`
				} `json:"schema"`
			} `json:"parameters"`
		} `json:"paths"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	enums := func(path, name string) string {
		for _, parameter := range doc.Paths[path]["get"].Parameters {
			if parameter.Name == name {
				return strings.Join(parameter.Schema.Enum, ",")
			}
		}
		return "(missing)"
	}
	if got, want := enums("/public/v1/leagues/{league}/leaderboards", "metric"), strings.Join([]string{string(MetricMMR), string(MetricHeirRating), string(MetricWins), string(MetricLosses)}, ","); got != want {
		t.Errorf("metric: spec %s, sdk %s", got, want)
	}
	if got, want := enums("/public/v1/leagues/{league}/fixtures", "status"), strings.Join([]string{string(FixtureScheduled), string(FixturePlayed), string(FixtureCancelled)}, ","); got != want {
		t.Errorf("status: spec %s, sdk %s", got, want)
	}
	if got, want := enums("/public/v1/leagues/{league}/leaderboards", "category"), strings.Join([]string{string(CategoryOverall), string(CategoryCompetitive), string(CategoryCasual)}, ","); got != want {
		t.Errorf("category: spec %s, sdk %s", got, want)
	}
}
