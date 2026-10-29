package heir

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"math/rand/v2"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
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

// NewClient makes a client. Reads need no option at all.
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
		option(c)
	}
	c.Stats = &Stats{client: c}
	return c
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

// WithHeader adds a header to one call.
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

var maxAgePattern = regexp.MustCompile(`(?i)\bmax-age=(\d+)`)

// do sends a call and decodes its answer into out, retrying and caching as the client is configured to.
func (c *Client) do(ctx context.Context, call call, out any, options ...RequestOption) error {
	var opts requestOptions
	for _, option := range options {
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
	useCache := call.cacheable && c.cacheEnabled && !opts.noCache
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
				if err := c.sleep(ctx, backoff(attempt)); err != nil {
					return err
				}
				continue
			}
			return err
		}
		if response.StatusCode == http.StatusNotModified && cached != nil {
			c.cache.put(cacheKey, &cacheEntry{etag: cached.etag, body: cached.body, freshUntil: c.freshUntil(response.Header)})
			return json.Unmarshal(cached.body, out)
		}
		if response.StatusCode >= 200 && response.StatusCode < 300 {
			if useCache {
				c.store(cacheKey, response.Header, body)
			}
			if out == nil || response.StatusCode == http.StatusNoContent {
				return nil
			}
			return json.Unmarshal(body, out)
		}
		apiErr := newAPIError(response, body)
		retryable := apiErr.StatusCode == 429 || apiErr.StatusCode == 503 ||
			(call.idempotent && (apiErr.StatusCode == 500 || apiErr.StatusCode == 502 || apiErr.StatusCode == 504))
		if retryable && attempt < c.maxRetries {
			delay := backoff(attempt)
			if apiErr.RetryAfter > 0 || response.Header.Get("Retry-After") != "" {
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
	defer response.Body.Close()
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
	timedOut := attemptCtx.Err() != nil
	return &ConnectionError{URL: target, Err: err, Timeout: timedOut}
}

func (c *Client) store(key string, header http.Header, body []byte) {
	control := header.Get("Cache-Control")
	if strings.Contains(strings.ToLower(control), "no-store") {
		return
	}
	etag := header.Get("ETag")
	until := c.freshUntil(header)
	if etag == "" && until.IsZero() {
		return
	}
	c.cache.put(key, &cacheEntry{etag: etag, body: body, freshUntil: until})
}

// freshUntil is when an answer stops being fresh, from its Cache-Control max-age; the zero time when it has none.
func (c *Client) freshUntil(header http.Header) time.Time {
	match := maxAgePattern.FindStringSubmatch(header.Get("Cache-Control"))
	if match == nil {
		return time.Time{}
	}
	seconds, _ := strconv.Atoi(match[1])
	return c.now().Add(time.Duration(seconds) * time.Second)
}

// backoff is 500 ms, 1 s, 2 s, ... with jitter, capped at 8 s.
func backoff(attempt int) time.Duration {
	base := 500 * time.Millisecond << uint(attempt)
	if base > 8*time.Second {
		base = 8 * time.Second
	}
	return time.Duration(float64(base) * (0.75 + rand.Float64()*0.5))
}
