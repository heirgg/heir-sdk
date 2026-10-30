package heir

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestInvalidRetryAfterUsesBackoff(t *testing.T) {
	for _, header := range []string{"NaN", "Inf", "-Inf", "1e1000", "-1", "invalid"} {
		t.Run(header, func(t *testing.T) {
			h := newHarness([]step{apiError(429, "rate-limited", "Wait.", "Retry-After", header), respond(200, `{"items":[],"credentials":[]}`)})
			if _, err := h.League("nacl").Items(context.Background()); err != nil {
				t.Fatal(err)
			}
			if len(h.sleeps) != 1 || h.sleeps[0] <= 0 {
				t.Fatalf("invalid header %q bypassed backoff: %v", header, h.sleeps)
			}
		})
	}
}

func TestOversizedRetryAfterCannotOverflowDelayLimit(t *testing.T) {
	for _, header := range []string{"1e100", "9223372036.854776", "9999999999999999999999999999"} {
		t.Run(header, func(t *testing.T) {
			h := newHarness([]step{apiError(429, "rate-limited", "Wait.", "Retry-After", header)})
			_, err := h.League("nacl").Items(context.Background())
			var apiErr *APIError
			if !errors.As(err, &apiErr) || apiErr.RetryAfter != time.Duration(1<<63-1) || h.api.calls() != 1 || len(h.sleeps) != 0 {
				t.Fatalf("error=%v requests=%d waits=%v", err, h.api.calls(), h.sleeps)
			}
		})
	}
}

func TestZeroRetryAfterAllowsImmediateRetry(t *testing.T) {
	h := newHarness([]step{apiError(429, "rate-limited", "Retry.", "Retry-After", "0"), respond(200, `{"items":[],"credentials":[]}`)}, WithMaxRetryDelay(0))
	if _, err := h.League("nacl").Items(context.Background()); err != nil {
		t.Fatal(err)
	}
	if len(h.sleeps) != 1 || h.sleeps[0] != 0 {
		t.Fatalf("waits=%v", h.sleeps)
	}
}
