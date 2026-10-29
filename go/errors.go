package heir

import (
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"strconv"
	"time"
)

// APIIssue is one field the API could not accept, named when it can be.
type APIIssue struct {
	Path    string `json:"path"`
	Message string `json:"message"`
}

// APIError is an answer from the API that was an error. Code is the stable code to branch on (`rate-limited`,
// `league-not-found`, `rejected`, ...), Message a sentence for a person whose wording can change. StatusCode is the
// HTTP status and RetryAfter, on a 429, how long the API asked you to wait (zero when it did not say).
//
//	var apiErr *heir.APIError
//	if errors.As(err, &apiErr) && apiErr.Code == "league-not-found" { ... }
type APIError struct {
	StatusCode int
	Code       string
	Message    string
	Issues     []APIIssue
	RetryAfter time.Duration
	Header     http.Header
	// Body is the answer as it arrived, for an error that is not the API's envelope (a gateway page, say).
	Body []byte
}

func (e *APIError) Error() string {
	return fmt.Sprintf("heir: %s (%d): %s", e.Code, e.StatusCode, e.Message)
}

// IsRateLimited reports a 429: too many requests this minute, or as many live sessions open as the plan allows.
func (e *APIError) IsRateLimited() bool {
	return e.StatusCode == http.StatusTooManyRequests
}

// ConnectionError means the API could not be reached, or no answer arrived: Err is the underlying failure, and
// Timeout is true when the attempt ran out of time rather than failing outright.
type ConnectionError struct {
	URL     string
	Err     error
	Timeout bool
}

func (e *ConnectionError) Error() string {
	if e.Timeout {
		return fmt.Sprintf("heir: no answer from %s in time", e.URL)
	}
	return fmt.Sprintf("heir: could not reach %s: %v", e.URL, e.Err)
}

func (e *ConnectionError) Unwrap() error { return e.Err }

// newAPIError reads the API's `{error, message, issues?}` envelope; an answer that is not one still becomes an error you can inspect.
func newAPIError(response *http.Response, body []byte) *APIError {
	apiErr := &APIError{StatusCode: response.StatusCode, Code: "unknown", Header: response.Header, Body: body, RetryAfter: parseRetryAfter(response.Header.Get("Retry-After"))}
	var envelope struct {
		Error   string     `json:"error"`
		Message string     `json:"message"`
		Issues  []APIIssue `json:"issues"`
	}
	if json.Unmarshal(body, &envelope) == nil && envelope.Error != "" && envelope.Message != "" {
		apiErr.Code, apiErr.Message, apiErr.Issues = envelope.Error, envelope.Message, envelope.Issues
	} else {
		apiErr.Message = fmt.Sprintf("The API answered %d %s.", response.StatusCode, http.StatusText(response.StatusCode))
	}
	return apiErr
}

// parseRetryAfter reads either form the header takes: a count of seconds or an HTTP date.
func parseRetryAfter(header string) time.Duration {
	if header == "" {
		return 0
	}
	if seconds, err := strconv.ParseFloat(header, 64); err == nil {
		return time.Duration(math.Max(0, seconds) * float64(time.Second))
	}
	if at, err := http.ParseTime(header); err == nil {
		if wait := time.Until(at); wait > 0 {
			return wait.Round(time.Second)
		}
	}
	return 0
}
