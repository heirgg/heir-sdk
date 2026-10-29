package heir

import (
	"sync"
	"time"
)

const maxCacheEntries = 1000

type cacheEntry struct {
	etag string
	body []byte
	// freshUntil is when the entry stops being served without asking the API; the zero time means always revalidate.
	freshUntil time.Time
}

// cache keeps League reads as the API's Cache-Control allows. It is bounded: when full it starts over, which only
// costs a request per question.
type cache struct {
	mu      sync.Mutex
	entries map[string]*cacheEntry
}

func (c *cache) get(key string) *cacheEntry {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.entries[key]
}

func (c *cache) put(key string, entry *cacheEntry) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.entries == nil || len(c.entries) >= maxCacheEntries {
		c.entries = make(map[string]*cacheEntry)
	}
	c.entries[key] = entry
}

func (c *cache) clear() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.entries = nil
}
