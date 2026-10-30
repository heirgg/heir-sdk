package heir

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"math/rand/v2"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// DefaultBaseURL is the production API.
const DefaultBaseURL = "https://api.heir.gg"

// Client talks to the Heir API. Make one with NewClient and share it: it is safe for concurrent use and keeps a
// small cache of League reads.
type Client struct {
	// Stats is stat submission for the key's League.
	Stats *Stats

	apiKey        string
	baseURL       string
	http          *http.Client
	maxRetries    int
	maxRetryDelay time.Duration
	timeout       time.Duration
	cacheEnabled  bool
	cache         cache
	userAgent     string
	configErr     error

	// Replaced by tests.
	sleep func(ctx context.Context, d time.Duration) error
	now   func() time.Time
}

// Option configures a Client.
type Option func(*Client)

// WithAPIKey sets a League developer key, from Manage League, Developer, API keys. Without one, League reads work
// at 120 requests a minute per address. Call from your server: never put a key in a game client or browser.
func WithAPIKey(key string) Option { return func(c *Client) { c.apiKey = strings.TrimSpace(key) } }

// WithBaseURL points the client somewhere other than the production API.
func WithBaseURL(baseURL string) Option {
	return func(c *Client) { c.baseURL = strings.TrimRight(baseURL, "/") }
}

// WithHTTPClient sets the http.Client to send with: a proxy, a transport, or a fake for tests.
func WithHTTPClient(client *http.Client) Option { return func(c *Client) { c.http = client } }

// WithMaxRetries sets how many times a request is sent again after a 429, a 503, or (for a read or a write carrying
// an Idempotency-Key) a connection failure or gateway error, waiting as Retry-After says or with increasing backoff.
// The default is 2.
func WithMaxRetries(n int) Option { return func(c *Client) { c.maxRetries = n } }

// WithMaxRetryDelay sets the longest the client waits before one retry. A Retry-After beyond it is not waited for:
// the error is returned with RetryAfter set. The default is 30 seconds.
func WithMaxRetryDelay(d time.Duration) Option { return func(c *Client) { c.maxRetryDelay = d } }

// WithTimeout sets how long one attempt may take before it fails with a ConnectionError whose Timeout is true. The
// default is 30 seconds; zero disables it, leaving the context in charge.
func WithTimeout(d time.Duration) Option { return func(c *Client) { c.timeout = d } }

// WithoutCache stops the client keeping League reads as the API's Cache-Control allows. With the cache (the default),
// a server asking on every event spends one request a minute per question and revalidates with ETag after that.
// Paginated and stat answers are never cached: the API marks them no-store.
func WithoutCache() Option { return func(c *Client) { c.cacheEnabled = false } }

// WithUserAgent adds to the User-Agent, to say which integration is calling.
func WithUserAgent(agent string) Option { return func(c *Client) { c.userAgent = agent } }

// NewClient makes a client. Reads need no option at all. Invalid configuration is returned by Validate and by
// every request before any network activity, preserving the constructor's single return value.
func NewClient(options ...Option) *Client {
	c := &Client{
		baseURL:       DefaultBaseURL,
		http:          &http.Client{},
		maxRetries:    2,
		maxRetryDelay: 30 * time.Second,
		timeout:       30 * time.Second,
		cacheEnabled:  true,
		now:           time.Now,
	}
	c.sleep = func(ctx context.Context, d time.Duration) error {
		timer := time.NewTimer(d)
		defer timer.Stop()
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-timer.C:
			return nil
		}
	}
	for _, option := range options {
		if option == nil {
			c.configErr = &ConfigError{Field: "option", Message: "must not be nil"}
			continue
		}
		option(c)
	}
	c.Stats = &Stats{client: c}
	if c.configErr == nil {
		c.configErr = c.validateConfig()
	}
	return c
}

// Validate reports invalid client configuration. Call it at startup to fail before the first API request.
func (c *Client) Validate() error { return c.configErr }

func (c *Client) validateConfig() error {
	u, err := url.Parse(c.baseURL)
	if err != nil || u.Hostname() == "" || (u.Scheme != "https" && u.Scheme != "http") || u.User != nil || u.RawQuery != "" || u.ForceQuery || strings.Contains(c.baseURL, "#") {
		return &ConfigError{Field: "baseURL", Message: "must be an absolute HTTP or HTTPS URL without credentials, query, or fragment"}
	}
	if c.http == nil {
		return &ConfigError{Field: "httpClient", Message: "must not be nil"}
	}
	if c.maxRetries < 0 {
		return &ConfigError{Field: "maxRetries", Message: "must be non-negative"}
	}
	if c.maxRetryDelay < 0 {
		return &ConfigError{Field: "maxRetryDelay", Message: "must be non-negative"}
	}
	if c.timeout < 0 {
		return &ConfigError{Field: "timeout", Message: "must be non-negative"}
	}
	if strings.ContainsAny(c.apiKey, "\r\n") || strings.ContainsAny(c.userAgent, "\r\n") {
		return &ConfigError{Field: "headers", Message: "API key and user agent must not contain newlines"}
	}
	return nil
}

// League gives one League's public reads, by vanity name (`heir.gg/nacl`) or Discord server ID.
func (c *Client) League(ref string) *League {
	return &League{client: c, Ref: ref, base: "/public/v1/leagues/" + url.PathEscape(ref)}
}

// Authenticated reports whether calls carry a developer key.
func (c *Client) Authenticated() bool { return c.apiKey != "" }

// ClearCache forgets every cached League read.
func (c *Client) ClearCache() { c.cache.clear() }

// RequestOption adjusts one call.
type RequestOption func(*requestOptions)

type requestOptions struct {
	idempotencyKey string
	dryRun         bool
	noCache        bool
	header         http.Header
}

// WithIdempotencyKey sets a stat tracking write's Idempotency-Key: your own value unique to this request. The client
// generates one per call, so its own retries never write twice; set it yourself when your code may send the same
// request again later, so the API answers as it did the first time.
func WithIdempotencyKey(key string) RequestOption {
	return func(o *requestOptions) { o.idempotencyKey = key }
}

// DryRun checks a stat tracking write without storing anything: the answer says what would have happened.
func DryRun() RequestOption { return func(o *requestOptions) { o.dryRun = true } }

// NoCache asks the API even when a fresh cached answer exists.
func NoCache() RequestOption { return func(o *requestOptions) { o.noCache = true } }

// WithHeader adds a header to one call. Calls with custom headers bypass the cache so credentials and other
// response-varying values cannot reuse another request's answer.
func WithHeader(name, value string) RequestOption {
	return func(o *requestOptions) {
		if o.header == nil {
			o.header = http.Header{}
		}
		o.header.Add(name, value)
	}
}

// call is one API call as the resources describe it to the transport.
type call struct {
	method string
	// path with its parameters already escaped, such as /public/v1/leagues/nacl/rosters.
	path  string
	query url.Values
	body  any
	// idempotent: safe to send again after a connection failure or gateway error. Every read, and a write carrying an Idempotency-Key.
	idempotent bool
	// cacheable: a read whose answer may be kept as its Cache-Control says.
	cacheable bool
}

// do sends a call and decodes its answer into out, retrying and caching as the client is configured to.
func (c *Client) do(ctx context.Context, call call, out any, options ...RequestOption) error {
	if err := c.Validate(); err != nil {
		return err
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	var opts requestOptions
	for _, option := range options {
		if option == nil {
			return &ConfigError{Field: "requestOption", Message: "must not be nil"}
		}
		option(&opts)
	}
	if opts.dryRun {
		if call.query == nil {
			call.query = url.Values{}
		}
		call.query.Set("dryRun", "true")
	}
	target := c.baseURL + call.path
	if len(call.query) > 0 {
		target += "?" + call.query.Encode()
	}
	useCache := call.cacheable && c.cacheEnabled && !opts.noCache && len(opts.header) == 0
	cacheKey := "anon " + target
	if c.apiKey != "" {
		cacheKey = "key " + target
	}
	var cached *cacheEntry
	if useCache {
		if cached = c.cache.get(cacheKey); cached != nil && cached.freshUntil.After(c.now()) {
			return json.Unmarshal(cached.body, out)
		}
	}

	var payload []byte
	if call.body != nil {
		var err error
		if payload, err = json.Marshal(call.body); err != nil {
			return err
		}
	}
	header := http.Header{}
	for name, values := range opts.header {
		header[name] = values
	}
	header.Set("Accept", "application/json")
	if payload != nil {
		header.Set("Content-Type", "application/json")
	}
	if c.apiKey != "" {
		header.Set("Authorization", "Bearer "+c.apiKey)
	}
	if opts.idempotencyKey != "" {
		header.Set("Idempotency-Key", opts.idempotencyKey)
	}
	if cached != nil && cached.etag != "" {
		header.Set("If-None-Match", cached.etag)
	}
	agent := "heir-sdk-go/" + Version
	if c.userAgent != "" {
		agent += " " + c.userAgent
	}
	header.Set("User-Agent", agent)

	for attempt := 0; ; attempt++ {
		response, body, err := c.send(ctx, call.method, target, header, payload)
		if err != nil {
			var connErr *ConnectionError
			if errors.As(err, &connErr) && !connErr.Timeout && call.idempotent && attempt < c.maxRetries {
				delay := backoff(attempt)
				if delay > c.maxRetryDelay {
					return err
				}
				if err := c.sleep(ctx, delay); err != nil {
					return err
				}
				continue
			}
			return err
		}
		if response.StatusCode == http.StatusNotModified && cached != nil {
			c.store(cacheKey, revalidatedHeader(cached.header, response.Header), cached.body)
			return json.Unmarshal(cached.body, out)
		}
		if response.StatusCode >= 200 && response.StatusCode < 300 {
			if out != nil && response.StatusCode != http.StatusNoContent {
				if err := json.Unmarshal(body, out); err != nil {
					return err
				}
			}
			if useCache {
				c.store(cacheKey, response.Header, body)
			}
			return nil
		}
		apiErr := newAPIError(response, body)
		retryable := apiErr.StatusCode == 429 || apiErr.StatusCode == 503 ||
			(call.idempotent && (apiErr.StatusCode == 500 || apiErr.StatusCode == 502 || apiErr.StatusCode == 504))
		if retryable && attempt < c.maxRetries {
			delay := backoff(attempt)
			if apiErr.retryAfterValid {
				delay = apiErr.RetryAfter
			}
			if delay <= c.maxRetryDelay {
				if err := c.sleep(ctx, delay); err != nil {
					return err
				}
				continue
			}
		}
		return apiErr
	}
}

// send makes one attempt, within the client's timeout, and reads the whole answer.
func (c *Client) send(ctx context.Context, method, target string, header http.Header, payload []byte) (*http.Response, []byte, error) {
	attemptCtx, cancel := ctx, func() {}
	if c.timeout > 0 {
		attemptCtx, cancel = context.WithTimeout(ctx, c.timeout)
	}
	defer cancel()
	var reader io.Reader
	if payload != nil {
		reader = bytes.NewReader(payload)
	}
	request, err := http.NewRequestWithContext(attemptCtx, method, target, reader)
	if err != nil {
		return nil, nil, err
	}
	request.Header = header.Clone()
	response, err := c.http.Do(request)
	if err != nil {
		return nil, nil, c.connectionError(ctx, attemptCtx, target, err)
	}
	defer func() {
		// The response is read in full below; a cleanup error must not trigger another write.
		_ = response.Body.Close()
	}()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		return nil, nil, c.connectionError(ctx, attemptCtx, target, err)
	}
	return response, body, nil
}

// connectionError tells a caller's own cancellation (returned as it is) from a timed-out attempt and a failed connection.
func (c *Client) connectionError(ctx, attemptCtx context.Context, target string, err error) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	var timeoutErr net.Error
	timedOut := attemptCtx.Err() != nil || errors.Is(err, context.DeadlineExceeded) || (errors.As(err, &timeoutErr) && timeoutErr.Timeout())
	return &ConnectionError{URL: target, Err: err, Timeout: timedOut}
}

// backoff is 500 ms, 1 s, 2 s, ... with jitter, capped at 8 s.
func backoff(attempt int) time.Duration {
	base := 8 * time.Second
	if attempt < 4 {
		base = 500 * time.Millisecond << uint(attempt)
	}
	return min(8*time.Second, time.Duration(float64(base)*(0.75+rand.Float64()*0.5)))
}
