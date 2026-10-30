import {afterEach, describe, expect, it, vi} from "vitest";
import {Heir, HeirError, HeirTimeoutError} from "../src/index.js";

const json = (body: unknown, headers: Record<string, string> = {}) => new Response(JSON.stringify(body), {headers});
afterEach(() => vi.useRealTimers());

describe("request lifecycle regressions", () => {
  const stream = (status = 200): typeof fetch => async (_url, init) => new Response(new ReadableStream({
    start(controller) {
      const timer = setTimeout(() => { controller.enqueue(new TextEncoder().encode("{}")); controller.close(); }, 200);
      init?.signal?.addEventListener("abort", () => { clearTimeout(timer); controller.error(init.signal?.reason); }, {once: true});
    }
  }), {status});

  it.each([200, 503])("enforces the attempt timeout through body consumption (status %i)", async status => {
    vi.useFakeTimers();
    const pending = new Heir({fetch: stream(status), timeoutMs: 25}).league("nacl").config().catch(e => e);
    await vi.runAllTimersAsync();
    expect(await pending).toBeInstanceOf(HeirTimeoutError);
  });

  it("keeps caller cancellation active after headers", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const reason = new Error("caller stopped");
    const pending = new Heir({fetch: stream()}).league("nacl").config({signal: controller.signal}).catch(e => e);
    await vi.advanceTimersByTimeAsync(1);
    controller.abort(reason);
    await vi.runAllTimersAsync();
    expect(await pending).toBe(reason);
  });

  it("aborts a retry wait immediately without another fetch", async () => {
    vi.useFakeTimers();
    const controller = new AbortController();
    const fetch = vi.fn(async () => new Response('{"error":"rate-limited","message":"Wait"}', {status: 429, headers: {"retry-after": "30"}}));
    let settled = false;
    const pending = new Heir({fetch}).league("nacl").config({signal: controller.signal}).catch(e => { settled = true; return e; });
    await vi.advanceTimersByTimeAsync(1);
    controller.abort(new Error("stopped"));
    await vi.advanceTimersByTimeAsync(1);
    const settledAtAbort = settled;
    await vi.runAllTimersAsync();
    await pending;
    expect(settledAtAbort).toBe(true);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("applies the retry delay limit to connection failures", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn(async () => { throw new Error("reset"); });
    const pending = new Heir({fetch, maxRetries: 1, maxRetryDelayMs: 0}).league("nacl").config().catch(e => e);
    await vi.runAllTimersAsync();
    expect(await pending).toBeInstanceOf(HeirError);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("retries body-stream failures for a read", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn<typeof globalThis.fetch>()
      .mockResolvedValueOnce(new Response(new ReadableStream({start(controller) { controller.error(new Error("stream reset")); }})))
      .mockResolvedValueOnce(json({items: []}));
    const pending = new Heir({fetch}).league("nacl").items().catch(e => e);
    await vi.runAllTimersAsync();
    expect(await pending).toEqual({items: []});
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("wraps malformed success JSON in an SDK error", async () => {
    const error = await new Heir({fetch: async () => new Response("not JSON")}).league("nacl").config().catch(e => e);
    expect(error).toBeInstanceOf(HeirError);
    expect(error.name).toBe("HeirProtocolError");
    expect(error.status).toBe(200);
    expect(error.cause).toBeInstanceOf(SyntaxError);
  });

  it.each(["null", "[]", "123"])("rejects a non-object success response %s", async body => {
    const failure = await new Heir({fetch: async () => new Response(body)}).league("nacl").config().catch(e => e);
    expect(failure.name).toBe("HeirProtocolError");
  });

  it("rejects an unexpected empty 204 response through the protocol error", async () => {
    const failure = await new Heir({fetch: async () => new Response(null, {status: 204})}).league("nacl").rosters().catch(e => e);
    expect(failure.name).toBe("HeirProtocolError");
    expect(failure.status).toBe(204);
  });

  it("keeps malformed optional error issues from replacing the HTTP error", async () => {
    const failure = await new Heir({fetch: async () => new Response(JSON.stringify({error: "bad-input", message: "Invalid", issues: ["bad", null, {path: "x", message: "fix"}]}), {status: 400})}).league("nacl").config().catch(e => e);
    expect(failure.name).toBe("HeirApiError");
    expect(failure.issues).toEqual([{path: "x", message: "fix"}]);
  });
});

describe("cache isolation and freshness", () => {
  it("does not share mutable response objects with the cache", async () => {
    const fetch = vi.fn(async () => json({items: [{key: "gold"}]}, {"cache-control": "max-age=60"}));
    const league = new Heir({fetch}).league("nacl");
    const first = await league.inventory("steam", "id");
    first.items.length = 0;
    expect((await league.inventory("steam", "id")).items).toHaveLength(1);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("bypasses caching when any custom headers are supplied", async () => {
    const fetch = vi.fn(async (_url, init) => json({auth: new Headers(init?.headers).get("Authorization")}, {"cache-control": "max-age=60", "vary": "Authorization"}));
    const league = new Heir({fetch}).league("nacl");
    await league.config({headers: {Authorization: "Bearer A"}});
    expect(await league.config({headers: {Authorization: "Bearer B"}})).toEqual({auth: "Bearer B"});
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it.each([
    {"cache-control": "no-cache, max-age=60"},
    {"cache-control": "max-age=60", age: "60"},
    {"cache-control": "max-age=60", vary: "*"},
    {"cache-control": "max-age=60", vary: "Accept-Language"}
  ])("does not serve a fresh cached response for %j", async headers => {
    const fetch = vi.fn(async () => json({items: []}, headers));
    const league = new Heir({fetch}).league("nacl");
    await league.items(); await league.items();
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("subtracts apparent age from the response Date", async () => {
    vi.useFakeTimers({now: Date.parse("2026-10-30T12:00:00Z")});
    const fetch = vi.fn(async () => json({items: []}, {"cache-control": "max-age=60", date: "Fri, 30 Oct 2026 11:59:00 GMT"}));
    const league = new Heir({fetch}).league("nacl");
    await league.items(); await league.items();
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("honors a pre-aborted signal even when a cached answer is fresh", async () => {
    const fetch = vi.fn(async () => json({items: []}, {"cache-control": "max-age=60"}));
    const league = new Heir({fetch}).league("nacl");
    await league.items();
    const reason = new Error("stopped");
    expect(await league.items({signal: AbortSignal.abort(reason)}).catch(e => e)).toBe(reason);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("merges 304 metadata and uses the updated validator", async () => {
    vi.useFakeTimers({now: 1_000_000});
    const fetch = vi.fn<typeof globalThis.fetch>()
      .mockResolvedValueOnce(json({items: []}, {"cache-control": "max-age=60", etag: '"old"'}))
      .mockResolvedValueOnce(new Response(null, {status: 304, headers: {etag: '"new"'}}))
      .mockResolvedValueOnce(new Response(null, {status: 304}));
    const league = new Heir({fetch}).league("nacl");
    await league.items();
    vi.advanceTimersByTime(61_000);
    await league.items(); await league.items();
    expect(fetch).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(61_000);
    await league.items();
    expect(new Headers(fetch.mock.calls[2]?.[1]?.headers).get("if-none-match")).toBe('"new"');
  });

  it("removes a prior cache entry when revalidation says no-store", async () => {
    vi.useFakeTimers({now: 1_000_000});
    const fetch = vi.fn<typeof globalThis.fetch>()
      .mockResolvedValueOnce(json({items: []}, {"cache-control": "max-age=1", etag: '"old"'}))
      .mockResolvedValueOnce(new Response(null, {status: 304, headers: {"cache-control": "no-store"}}))
      .mockResolvedValueOnce(json({items: []}));
    const league = new Heir({fetch}).league("nacl");
    await league.items(); vi.advanceTimersByTime(2000); await league.items(); await league.items();
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(new Headers(fetch.mock.calls[2]?.[1]?.headers).has("if-none-match")).toBe(false);
  });
});

describe("input and continuation boundaries", () => {
  it.each([{maxRetries: -1}, {maxRetries: 1.5}, {maxRetries: Infinity}, {maxRetryDelayMs: NaN}, {timeoutMs: 0}, {timeoutMs: Infinity}, {baseUrl: "broken"}, {baseUrl: "https://example.test/?"}, {baseUrl: "https://example.test/#"}])("rejects invalid configuration %j", options => {
    expect(() => new Heir(options)).toThrow(HeirError);
  });

  it.each([{apiKey: 3}, {cache: "false"}, {userAgent: 3}, {fetch: 3}, {maxRetryDelayMs: 3_000_000_000}])("rejects malformed JavaScript configuration %j", options => {
    expect(() => new Heir(options as never)).toThrow(HeirError);
  });

  it("wraps JSON encoding failures", async () => {
    const cyclic: Record<string, unknown> = {}; cyclic.self = cyclic;
    const failure = await new Heir().league("nacl").lookupPlayers(cyclic as never).catch(e => e);
    expect(failure).toBeInstanceOf(HeirError);
    expect(failure.name).toBe("HeirInputError");
  });

  it("rejects invalid per-call limits before using cache", async () => {
    const league = new Heir({fetch: async () => json({items: []}, {"cache-control": "max-age=60"})}).league("nacl");
    await league.items();
    expect(await league.items({maxRetries: -1}).catch(e => e)).toBeInstanceOf(HeirError);
    expect(await league.items({timeoutMs: NaN}).catch(e => e)).toBeInstanceOf(HeirError);
  });

  it("wraps invalid header values before contacting the API", async () => {
    const fetch = vi.fn(async () => json({}));
    const failure = await new Heir({fetch}).league("nacl").items({headers: {"X-Invalid": "line\nbreak"}}).catch(e => e);
    expect(failure.name).toBe("HeirInputError");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rejects empty explicit idempotency keys", async () => {
    const fetch = vi.fn(async () => json({}));
    const failure = await new Heir({fetch}).stats.heartbeat("match", {idempotencyKey: ""}).catch(e => e);
    expect(failure).toBeInstanceOf(HeirError);
    expect(fetch).not.toHaveBeenCalled();
  });

  it.each([".", "..", "", "\ud800"])("rejects invalid League path input %j with an SDK error", ref => {
    expect(() => new Heir().league(ref)).toThrow(HeirError);
  });

  it("snapshots pagination filters and headers before callers can mutate them", async () => {
    const urls: string[] = [];
    const headers: Headers[] = [];
    const fetch: typeof globalThis.fetch = async (url, init) => {
      urls.push(String(url)); headers.push(new Headers(init?.headers));
      return json({rosters: [], page: 0, pageSize: 10, hasMore: urls.length === 1, nextToken: urls.length === 1 ? "next" : null});
    };
    const query = {category: "competitive" as const, pageSize: 10};
    const options = {headers: {"X-Integration": "original"}};
    const page = await new Heir({fetch}).league("nacl").rosters(query, options);
    query.pageSize = 20; options.headers["X-Integration"] = "changed";
    await page.next();
    expect(new URL(urls[1]!).searchParams.get("pageSize")).toBe("10");
    expect(headers[1]!.get("X-Integration")).toBe("original");
  });
});
