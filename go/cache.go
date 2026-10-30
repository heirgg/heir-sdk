package heir

import (
	"container/list"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"
)

const maxCacheEntries = 1000

type cacheEntry struct {
	etag   string
	body   []byte
	header http.Header
	// freshUntil is when the entry stops being served without asking the API; the zero time means always revalidate.
	freshUntil time.Time
}

type cachedValue struct {
	key   string
	entry *cacheEntry
}

// cache keeps the most recently used League reads. Entries are immutable once stored, so a caller can decode an
// answer after releasing the lock while other goroutines read, replace or evict entries.
type cache struct {
	mu      sync.Mutex
	entries map[string]*list.Element
	order   list.List
}

func (c *cache) get(key string) *cacheEntry {
	c.mu.Lock()
	defer c.mu.Unlock()
	if element := c.entries[key]; element != nil {
		c.order.MoveToFront(element)
		return element.Value.(cachedValue).entry
	}
	return nil
}

func (c *cache) put(key string, entry *cacheEntry) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.entries == nil {
		c.entries = make(map[string]*list.Element)
	}
	if element := c.entries[key]; element != nil {
		element.Value = cachedValue{key: key, entry: entry}
		c.order.MoveToFront(element)
		return
	}
	if len(c.entries) >= maxCacheEntries {
		oldest := c.order.Back()
		delete(c.entries, oldest.Value.(cachedValue).key)
		c.order.Remove(oldest)
	}
	c.entries[key] = c.order.PushFront(cachedValue{key: key, entry: entry})
}

func (c *cache) remove(key string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if element := c.entries[key]; element != nil {
		delete(c.entries, key)
		c.order.Remove(element)
	}
}

func (c *cache) clear() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.entries = nil
	c.order.Init()
}

func cacheDirectives(header http.Header) map[string]string {
	directives := make(map[string]string)
	for _, value := range header.Values("Cache-Control") {
		for _, directive := range strings.Split(value, ",") {
			name, value, _ := strings.Cut(strings.TrimSpace(directive), "=")
			directives[strings.ToLower(strings.TrimSpace(name))] = strings.Trim(strings.TrimSpace(value), `"`)
		}
	}
	return directives
}

func (c *Client) store(key string, header http.Header, body []byte) {
	directives := cacheDirectives(header)
	_, noStore := directives["no-store"]
	// Conservatively bypass Vary responses instead of guessing which request headers define a representation.
	if noStore || strings.TrimSpace(strings.Join(header.Values("Vary"), ",")) != "" {
		c.cache.remove(key)
		return
	}
	etag := header.Get("ETag")
	until := c.freshUntil(header)
	if etag == "" && until.IsZero() {
		c.cache.remove(key)
		return
	}
	c.cache.put(key, &cacheEntry{etag: etag, body: body, header: header.Clone(), freshUntil: until})
}

// freshUntil accounts for time already spent in an upstream cache; no-cache always requires revalidation.
func (c *Client) freshUntil(header http.Header) time.Time {
	directives := cacheDirectives(header)
	if _, noCache := directives["no-cache"]; noCache {
		return time.Time{}
	}
	seconds, err := strconv.ParseInt(directives["max-age"], 10, 64)
	if err != nil || seconds < 0 {
		return time.Time{}
	}
	const maxSeconds = int64((1<<63 - 1) / time.Second)
	lifetime := time.Duration(min(seconds, maxSeconds)) * time.Second
	now := c.now()
	age := time.Duration(0)
	if seconds, err := strconv.ParseInt(header.Get("Age"), 10, 64); err == nil && seconds > 0 {
		age = time.Duration(min(seconds, maxSeconds)) * time.Second
	}
	if date, err := http.ParseTime(header.Get("Date")); err == nil {
		age = max(age, now.Sub(date))
	}
	return now.Add(max(time.Duration(0), lifetime-age))
}

// A 304 updates response metadata, retaining omitted cache directives and validators. Age and Date describe the
// new validation response, so old age metadata must not be carried into another freshness interval.
func revalidatedHeader(stored, response http.Header) http.Header {
	header := stored.Clone()
	if header == nil {
		header = make(http.Header)
	}
	header.Del("Age")
	header.Del("Date")
	for name, values := range response {
		header[name] = append([]string(nil), values...)
	}
	return header
}
