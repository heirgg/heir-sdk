package heir

import (
	"context"
	"errors"
	"io"
	"net/http"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

type transportTimeout struct{}

func (transportTimeout) Error() string   { return "transport timed out" }
func (transportTimeout) Timeout() bool   { return true }
func (transportTimeout) Temporary() bool { return true }

type timedOutBody struct{}

func (timedOutBody) Read([]byte) (int, error) { return 0, transportTimeout{} }
func (timedOutBody) Close() error             { return nil }

func TestCustomHTTPTimeoutsAreNotRetried(t *testing.T) {
	cases := []struct {
		name      string
		timeout   time.Duration
		roundTrip roundTripFunc
	}{
		{name: "transport", roundTrip: func(*http.Request) (*http.Response, error) { return nil, transportTimeout{} }},
		{name: "client", timeout: time.Millisecond, roundTrip: func(r *http.Request) (*http.Response, error) { <-r.Context().Done(); return nil, r.Context().Err() }},
		{name: "response body", roundTrip: func(r *http.Request) (*http.Response, error) {
			return &http.Response{StatusCode: 200, Body: timedOutBody{}, Request: r}, nil
		}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			calls := 0
			c := NewClient(WithHTTPClient(&http.Client{Timeout: tc.timeout, Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) { calls++; return tc.roundTrip(r) })}))
			_, err := c.League("nacl").Config(context.Background())
			var timeout *ConnectionError
			if !errors.As(err, &timeout) || !timeout.Timeout || calls != 1 {
				t.Fatalf("err=%v calls=%d", err, calls)
			}
		})
	}
}

func TestRetryDelayCapAppliesToConnectionFailures(t *testing.T) {
	h := newHarness([]step{broken}, WithMaxRetryDelay(time.Millisecond))
	_, err := h.League("nacl").Items(context.Background())
	var connection *ConnectionError
	if !errors.As(err, &connection) || h.api.calls() != 1 || len(h.sleeps) != 0 {
		t.Fatalf("err=%v calls=%d waits=%v", err, h.api.calls(), h.sleeps)
	}
}

func TestRetryWaitObservesContext(t *testing.T) {
	api := &fakeAPI{steps: []step{apiError(429, "rate-limited", "Wait.", "Retry-After", "10")}}
	client := NewClient(WithHTTPClient(&http.Client{Transport: api}))
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()
	_, err := client.League("nacl").Items(ctx)
	if !errors.Is(err, context.DeadlineExceeded) || api.calls() != 1 {
		t.Fatalf("err=%v calls=%d", err, api.calls())
	}
}

func TestCanceledContextDoesNotServeCachedAnswer(t *testing.T) {
	h := newHarness([]step{respond(200, `{"items":[],"credentials":[]}`, "Cache-Control", "max-age=60")})
	if _, err := h.League("nacl").Items(context.Background()); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := h.League("nacl").Items(ctx); !errors.Is(err, context.Canceled) {
		t.Fatalf("err=%v", err)
	}
}

func TestInvalidConfigurationFailsBeforeNetworkActivity(t *testing.T) {
	cases := []struct {
		name, field string
		option      Option
	}{
		{"nil option", "option", nil},
		{"nil HTTP client", "httpClient", WithHTTPClient(nil)},
		{"negative retries", "maxRetries", WithMaxRetries(-1)},
		{"negative retry delay", "maxRetryDelay", WithMaxRetryDelay(-time.Second)},
		{"negative timeout", "timeout", WithTimeout(-time.Second)},
		{"relative URL", "baseURL", WithBaseURL("api.heir.gg")},
		{"URL credentials", "baseURL", WithBaseURL("https://user:secret@example.test")},
		{"URL query", "baseURL", WithBaseURL("https://example.test?key=secret")},
		{"empty URL query", "baseURL", WithBaseURL("https://example.test/?")},
		{"URL fragment", "baseURL", WithBaseURL("https://example.test#fragment")},
		{"empty URL fragment", "baseURL", WithBaseURL("https://example.test/#")},
		{"non HTTP URL", "baseURL", WithBaseURL("file:///tmp/api")},
		{"invalid key header", "headers", WithAPIKey("key\r\ninjected: secret")},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			h := newHarness(nil, tc.option)
			var invalid *ConfigError
			if !errors.As(h.Validate(), &invalid) || invalid.Field != tc.field {
				t.Fatalf("Validate=%v", h.Validate())
			}
			if _, err := h.League("nacl").Items(context.Background()); !errors.As(err, &invalid) {
				t.Fatalf("err=%v", err)
			}
			if h.api.calls() != 0 {
				t.Fatal("invalid config sent a request")
			}
		})
	}
	if err := NewClient(WithMaxRetries(0), WithTimeout(0), WithMaxRetryDelay(0)).Validate(); err != nil {
		t.Fatalf("zero options should be valid: %v", err)
	}
}

func TestNilRequestOptionsReturnConfigurationErrors(t *testing.T) {
	h := newHarness(nil)
	_, err := h.League("nacl").Items(context.Background(), nil)
	var invalid *ConfigError
	if !errors.As(err, &invalid) {
		t.Fatalf("read err=%v", err)
	}
	_, err = h.Stats.Heartbeat(context.Background(), "m1", nil)
	if !errors.As(err, &invalid) {
		t.Fatalf("write err=%v", err)
	}
}

func TestEmptyIdempotencyKeyGetsStableFallback(t *testing.T) {
	h := newHarness([]step{broken, respond(200, `{"deadline":1}`)})
	if _, err := h.Stats.Heartbeat(context.Background(), "m1", WithIdempotencyKey("")); err != nil {
		t.Fatal(err)
	}
	key := h.api.requests[0].Header.Get("Idempotency-Key")
	if !uuidPattern.MatchString(key) || h.api.requests[1].Header.Get("Idempotency-Key") != key {
		t.Fatal("missing or unstable fallback key")
	}
}

func TestSharedClientConcurrentReadsAndCacheClears(t *testing.T) {
	var requests atomic.Int64
	client := NewClient(WithHTTPClient(&http.Client{Transport: roundTripFunc(func(r *http.Request) (*http.Response, error) {
		requests.Add(1)
		return respond(200, `{"items":[],"credentials":[]}`, "Cache-Control", "max-age=60")(r)
	})}))
	var wg sync.WaitGroup
	for i := 0; i < 16; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < 30; j++ {
				if j%5 == 0 {
					client.ClearCache()
				}
				answer, err := client.League("nacl").Items(context.Background())
				if err != nil || answer == nil {
					t.Errorf("answer=%v err=%v", answer, err)
					return
				}
			}
		}()
	}
	wg.Wait()
	if requests.Load() == 0 {
		t.Fatal("no requests")
	}
}

func TestBackoffDoesNotOverflow(t *testing.T) {
	for _, attempt := range []int{0, 4, 32, 64, 1000} {
		if delay := backoff(attempt); delay <= 0 || delay > 8*time.Second {
			t.Errorf("attempt=%d delay=%v", attempt, delay)
		}
	}
}

var _ io.ReadCloser = timedOutBody{}
