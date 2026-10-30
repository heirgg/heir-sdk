package heir

import (
	"context"
	"fmt"
	"net/http"
	"testing"
	"time"
)

func TestCacheRevalidatesStaleAndVariantResponses(t *testing.T) {
	cases := []struct {
		name    string
		headers []string
	}{
		{"upstream age", []string{"Cache-Control", "max-age=60", "Age", "60"}},
		{"no-cache", []string{"Cache-Control", "max-age=60, no-cache"}},
		{"vary authorization", []string{"Cache-Control", "max-age=60", "Vary", "Authorization"}},
		{"vary star", []string{"Cache-Control", "max-age=60", "Vary", "*"}},
		{"old date", []string{"Cache-Control", "max-age=60", "Date", time.Date(2026, 10, 29, 11, 58, 0, 0, time.UTC).Format(http.TimeFormat)}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			h := newHarness([]step{respond(200, `{"items":[],"credentials":[]}`, tc.headers...), respond(200, `{"items":[],"credentials":[]}`)})
			for i := 0; i < 2; i++ {
				if _, err := h.League("nacl").Items(context.Background()); err != nil {
					t.Fatal(err)
				}
			}
			if h.api.calls() != 2 {
				t.Fatalf("requests=%d", h.api.calls())
			}
		})
	}
}

func TestCacheOnlyUsesRemainingFreshness(t *testing.T) {
	h := newHarness([]step{respond(200, `{"items":[],"credentials":[]}`, "Cache-Control", `max-age="60"`, "Age", "59"), respond(200, `{"items":[],"credentials":[]}`)})
	read := func() {
		t.Helper()
		if _, err := h.League("nacl").Items(context.Background()); err != nil {
			t.Fatal(err)
		}
	}
	read()
	read()
	if h.api.calls() != 1 {
		t.Fatal("fresh response was not reused")
	}
	h.clock = h.clock.Add(2 * time.Second)
	read()
	if h.api.calls() != 2 {
		t.Fatal("upstream age did not reduce freshness")
	}
}

func TestCacheBypassesAllCustomRequestHeaders(t *testing.T) {
	names := []string{"anonymous", "one", "two", "custom"}
	headers := []string{"", "Bearer one", "Bearer two", ""}
	steps := make([]step, 0, len(names))
	for i, name := range names {
		steps = append(steps, func(r *http.Request) (*http.Response, error) {
			if r.Header.Get("Authorization") != headers[i] {
				t.Errorf("authorization=%q", r.Header.Get("Authorization"))
			}
			return respond(200, fmt.Sprintf(`{"player":{"displayName":%q}}`, name), "Cache-Control", "max-age=60")(r)
		})
	}
	h := newHarness(steps)
	options := [][]RequestOption{nil, {WithHeader("Authorization", "Bearer one")}, {WithHeader("Authorization", "Bearer two")}, {WithHeader("X-Integration", "custom")}, nil}
	for i, opts := range options {
		answer, err := h.League("nacl").Player(context.Background(), "mordhau", "id", nil, opts...)
		if err != nil {
			t.Fatal(err)
		}
		want := names[0]
		if i < len(names) {
			want = names[i]
		}
		if answer.Player.DisplayName != want {
			t.Errorf("request=%d name=%q want=%q", i, answer.Player.DisplayName, want)
		}
	}
	if h.api.calls() != 4 {
		t.Fatalf("requests=%d", h.api.calls())
	}
}

func TestRevalidationMergesMetadataAndRemovesNoStore(t *testing.T) {
	h := newHarness([]step{
		respond(200, `{"items":[],"credentials":[]}`, "Cache-Control", "max-age=60", "ETag", `"v1"`, "Age", "59"),
		func(r *http.Request) (*http.Response, error) {
			if r.Header.Get("If-None-Match") != `"v1"` {
				t.Errorf("validator=%q", r.Header.Get("If-None-Match"))
			}
			return respond(304, "", "ETag", `"v2"`)(r)
		},
		func(r *http.Request) (*http.Response, error) {
			if r.Header.Get("If-None-Match") != `"v2"` {
				t.Errorf("updated validator=%q", r.Header.Get("If-None-Match"))
			}
			return respond(304, "", "Cache-Control", "no-store")(r)
		},
		func(r *http.Request) (*http.Response, error) {
			if r.Header.Get("If-None-Match") != "" {
				t.Error("no-store response retained its validator")
			}
			return respond(200, `{"items":[],"credentials":[]}`)(r)
		},
	})
	read := func() {
		t.Helper()
		if _, err := h.League("nacl").Items(context.Background()); err != nil {
			t.Fatal(err)
		}
	}
	read()
	h.clock = h.clock.Add(2 * time.Second)
	read()
	h.clock = h.clock.Add(2 * time.Second)
	read()
	if h.api.calls() != 2 {
		t.Fatal("304 lost max-age or retained old Age")
	}
	h.clock = h.clock.Add(60 * time.Second)
	read()
	read()
	if h.api.calls() != 4 {
		t.Fatalf("requests=%d", h.api.calls())
	}
}

func TestNoCacheResponsesRevalidateEveryTime(t *testing.T) {
	h := newHarness([]step{
		respond(200, `{"items":[],"credentials":[]}`, "Cache-Control", "no-cache, max-age=60", "ETag", `"v1"`),
		respond(304, ""), respond(304, ""),
	})
	for i := 0; i < 3; i++ {
		if _, err := h.League("nacl").Items(context.Background()); err != nil {
			t.Fatal(err)
		}
	}
	if h.api.calls() != 3 {
		t.Fatalf("requests=%d", h.api.calls())
	}
}

func TestCacheEvictsOnlyLeastRecentlyUsedEntry(t *testing.T) {
	var c cache
	for i := 0; i < maxCacheEntries; i++ {
		c.put(fmt.Sprint(i), &cacheEntry{})
	}
	if c.get("0") == nil {
		t.Fatal("entry missing")
	}
	c.put("new", &cacheEntry{})
	if c.get("0") == nil || c.get("new") == nil || c.get("999") == nil {
		t.Fatal("adding one entry removed unrelated entries")
	}
	if c.get("1") != nil {
		t.Fatal("least recently used entry survived")
	}
	c.put("new", &cacheEntry{})
	if c.get("2") == nil {
		t.Fatal("replacing an entry evicted another entry")
	}
}

func TestMalformedResponseDoesNotPopulateCache(t *testing.T) {
	h := newHarness([]step{respond(200, `<html>gateway error</html>`, "Cache-Control", "max-age=60"), respond(200, `{"items":[],"credentials":[]}`, "Cache-Control", "max-age=60")})
	if _, err := h.League("nacl").Items(context.Background()); err == nil {
		t.Fatal("malformed response was accepted")
	}
	if _, err := h.League("nacl").Items(context.Background()); err != nil {
		t.Fatal(err)
	}
	if h.api.calls() != 2 {
		t.Fatalf("requests=%d", h.api.calls())
	}
}
