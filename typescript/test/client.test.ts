import {afterEach, describe, expect, it, vi} from "vitest";
import {readFileSync} from "node:fs";
import {Heir, HeirApiError, HeirConnectionError, HeirTimeoutError, VERSION, type PlayerQuery} from "../src/index.js";

type Handler = (request: Request) => Response | Promise<Response>;

/** A fake API: each call is answered by the next handler, and every request is kept for inspection. */
const fakeApi = (...handlers: Handler[]) => {
  const requests: Request[] = [];
  const fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const request = new Request(input, init);
    requests.push(request);
    const handler = handlers.shift();
    if (!handler) throw new Error(`Unexpected request ${request.method} ${request.url}`);
    return handler(request);
  });
  return {fetch: fetch as unknown as typeof globalThis.fetch, requests, calls: () => fetch.mock.calls.length};
};
const json = (body: unknown, init: {status?: number; headers?: Record<string, string>} = {}) =>
  new Response(JSON.stringify(body), {status: init.status ?? 200, headers: {"content-type": "application/json", ...init.headers}});
const error = (status: number, code: string, message = "No.", headers: Record<string, string> = {}) => json({error: code, message}, {status, headers});

const PLAYER = {player: {identifier: "A1B2C3D4E5F67890", displayName: "Ada", profileUrl: null, mmr: null, rank: null, heirRating: null, roster: null}};

afterEach(() => {
  vi.useRealTimers();
});

describe("requests", () => {
  it("builds the URL from the League, path and defined query parameters, and sends the key as a bearer token", async () => {
    const api = fakeApi(() => json(PLAYER));
    const heir = new Heir({apiKey: "key-1", fetch: api.fetch, userAgent: "my-server/2.0"});
    // A field set to undefined is left out of the URL, for callers without exactOptionalPropertyTypes.
    const answer = await heir.league("nacl").player("mordhau", "A1B2C3D4E5F67890", {category: "competitive", gamemode: undefined} as unknown as PlayerQuery);
    expect(answer).toEqual(PLAYER);
    const [request] = api.requests;
    expect(request!.url).toBe("https://api.heir.gg/public/v1/leagues/nacl/players/mordhau/A1B2C3D4E5F67890?category=competitive");
    expect(request!.headers.get("authorization")).toBe("Bearer key-1");
    expect(request!.headers.get("accept")).toBe("application/json");
    expect(request!.headers.get("user-agent")).toBe(`heir-sdk-typescript/${VERSION} my-server/2.0`);
  });

  it("reads without a key when none is given, and encodes path segments", async () => {
    const api = fakeApi(() => json({fixture: {}}));
    const heir = new Heir({fetch: api.fetch, baseUrl: "https://staging.example.test/"});
    await heir.league("123456789012345678").fixture("a/b c");
    expect(heir.authenticated).toBe(false);
    expect(api.requests[0]!.url).toBe("https://staging.example.test/public/v1/leagues/123456789012345678/fixtures/a%2Fb%20c");
    expect(api.requests[0]!.headers.has("authorization")).toBe(false);
  });

  it("posts JSON bodies for the lookup reads", async () => {
    const api = fakeApi(() => json({players: []}));
    const heir = new Heir({fetch: api.fetch});
    await heir.league("nacl").lookupPlayers({credential: "steam", identifiers: ["76561198000000000"]});
    const request = api.requests[0]!;
    expect(request.method).toBe("POST");
    expect(request.headers.get("content-type")).toBe("application/json");
    expect(await request.json()).toEqual({credential: "steam", identifiers: ["76561198000000000"]});
  });
});

describe("errors", () => {
  it("turns the API's error envelope into a HeirApiError with its status, code, message and issues", async () => {
    const api = fakeApi(() => json({error: "invalid-request", message: "The match could not be read.", issues: [{path: "maps.0.winner", message: "Invalid option"}]}, {status: 400}));
    const heir = new Heir({apiKey: "k", fetch: api.fetch});
    const failure = await heir.stats.submitMatch({format: "heir-match-v1", startedAt: "2026-10-16T19:00:00Z", maps: []} as never).catch((e: unknown) => e);
    expect(failure).toBeInstanceOf(HeirApiError);
    const apiError = failure as HeirApiError;
    expect([apiError.status, apiError.code, apiError.message]).toEqual([400, "invalid-request", "The match could not be read."]);
    expect(apiError.issues).toEqual([{path: "maps.0.winner", message: "Invalid option"}]);
    expect(apiError.isRateLimited).toBe(false);
    expect(api.calls()).toBe(1);
  });

  it("still throws a HeirApiError for an answer that is not the envelope, such as a gateway page", async () => {
    const api = fakeApi(() => new Response("<html>bad gateway</html>", {status: 502, statusText: "Bad Gateway"}), () => new Response("<html>bad gateway</html>", {status: 502}), () => new Response("x", {status: 502}));
    const heir = new Heir({fetch: api.fetch, maxRetries: 2});
    vi.useFakeTimers();
    const pending = heir.league("nacl").config().catch((e: unknown) => e);
    await vi.runAllTimersAsync();
    const failure = await pending as HeirApiError;
    expect(failure).toBeInstanceOf(HeirApiError);
    expect([failure.status, failure.code, failure.body]).toEqual([502, "unknown", "x"]);
    expect(api.calls()).toBe(3);
  });

  it("wraps a failed connection and retries it for a read", async () => {
    const api = fakeApi(() => { throw new TypeError("fetch failed"); }, () => json({items: []}));
    const heir = new Heir({fetch: api.fetch});
    vi.useFakeTimers();
    const pending = heir.league("nacl").items();
    await vi.runAllTimersAsync();
    expect(await pending).toEqual({items: []});
    expect(api.calls()).toBe(2);
  });

  it("does not retry a connection failure for a complete-match submission without a reference", async () => {
    const api = fakeApi(() => { throw new TypeError("fetch failed"); });
    const heir = new Heir({apiKey: "k", fetch: api.fetch});
    const failure = await heir.stats.submitMatch({format: "heir-match-v1", startedAt: "2026-10-16T19:00:00Z", maps: []} as never).catch((e: unknown) => e);
    expect(failure).toBeInstanceOf(HeirConnectionError);
    expect((failure as HeirConnectionError).cause).toBeInstanceOf(TypeError);
    expect(api.calls()).toBe(1);
  });

  it("times out an attempt that gets no answer", async () => {
    const api = fakeApi(request => new Promise<Response>((_, reject) => request.signal.addEventListener("abort", () => reject(request.signal.reason))));
    const heir = new Heir({fetch: api.fetch, timeoutMs: 1000, maxRetries: 0});
    vi.useFakeTimers();
    const pending = heir.league("nacl").config().catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(1001);
    const failure = await pending;
    expect(failure).toBeInstanceOf(HeirTimeoutError);
    expect((failure as HeirTimeoutError).timeoutMs).toBe(1000);
  });

  it("rethrows the caller's own abort as it is", async () => {
    const api = fakeApi(request => new Promise<Response>((_, reject) => request.signal.addEventListener("abort", () => reject(request.signal.reason))));
    const heir = new Heir({fetch: api.fetch});
    const controller = new AbortController();
    const pending = heir.league("nacl").config({signal: controller.signal}).catch((e: unknown) => e);
    controller.abort(new Error("stopped"));
    expect(((await pending) as Error).message).toBe("stopped");
  });
});

describe("retries", () => {
  it("waits as Retry-After says after a 429, then succeeds", async () => {
    const api = fakeApi(() => error(429, "rate-limited", "Slow down.", {"retry-after": "2"}), () => json(PLAYER));
    const heir = new Heir({fetch: api.fetch});
    vi.useFakeTimers();
    const pending = heir.league("nacl").player("mordhau", "A1B2C3D4E5F67890");
    await vi.advanceTimersByTimeAsync(1999);
    expect(api.calls()).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(await pending).toEqual(PLAYER);
    expect(api.calls()).toBe(2);
  });

  it("gives up at once, with retryAfter set, when Retry-After is longer than it will wait", async () => {
    const api = fakeApi(() => error(429, "rate-limited", "Try again in a minute.", {"retry-after": "60"}));
    const heir = new Heir({fetch: api.fetch, maxRetryDelayMs: 30_000});
    const failure = await heir.league("nacl").config().catch((e: unknown) => e) as HeirApiError;
    expect([failure.code, failure.retryAfter, failure.isRateLimited]).toEqual(["rate-limited", 60, true]);
    expect(api.calls()).toBe(1);
  });

  it("stops after maxRetries and does not retry a 4xx that is not 429", async () => {
    const api = fakeApi(() => error(503, "unavailable"), () => error(503, "unavailable"), () => error(503, "unavailable"), () => error(503, "unavailable"));
    const heir = new Heir({fetch: api.fetch, maxRetries: 2});
    vi.useFakeTimers();
    const pending = heir.league("nacl").config().catch((e: unknown) => e);
    await vi.runAllTimersAsync();
    expect(((await pending) as HeirApiError).status).toBe(503);
    expect(api.calls()).toBe(3);

    const once = fakeApi(() => error(404, "league-not-found"));
    const failure = await new Heir({fetch: once.fetch}).league("nope").config().catch((e: unknown) => e) as HeirApiError;
    expect(failure.code).toBe("league-not-found");
    expect(once.calls()).toBe(1);
  });
});

describe("caching", () => {
  it("serves a fresh answer from memory for as long as Cache-Control allows, then revalidates with the ETag", async () => {
    const api = fakeApi(
      () => json({items: [{key: "gold"}]}, {headers: {etag: "\"v1\"", "cache-control": "public, max-age=60"}}),
      request => { expect(request.headers.get("if-none-match")).toBe("\"v1\""); return new Response(null, {status: 304, headers: {"cache-control": "public, max-age=60"}}); },
      () => json({items: []}, {headers: {etag: "\"v2\"", "cache-control": "public, max-age=60"}})
    );
    vi.useFakeTimers({now: 1_000_000});
    const heir = new Heir({fetch: api.fetch});
    const league = heir.league("nacl");
    expect(await league.inventory("mordhau", "A1B2C3D4E5F67890")).toEqual({items: [{key: "gold"}]});
    expect(await league.inventory("mordhau", "A1B2C3D4E5F67890")).toEqual({items: [{key: "gold"}]});
    expect(api.calls()).toBe(1);
    vi.setSystemTime(1_000_000 + 61_000);
    expect(await league.inventory("mordhau", "A1B2C3D4E5F67890")).toEqual({items: [{key: "gold"}]});
    expect(api.calls()).toBe(2);
    heir.clearCache();
    expect(await league.inventory("mordhau", "A1B2C3D4E5F67890")).toEqual({items: []});
    expect(api.calls()).toBe(3);
  });

  it("never caches an answer marked no-store, a paginated read, a write, or anything when caching is off", async () => {
    const page = {rosters: [], page: 0, pageSize: 25, hasMore: false, nextToken: null};
    const api = fakeApi(() => json(page, {headers: {"cache-control": "no-store", etag: "\"x\""}}), () => json(page, {headers: {"cache-control": "no-store", etag: "\"x\""}}));
    const heir = new Heir({fetch: api.fetch});
    await heir.league("nacl").rosters();
    await heir.league("nacl").rosters();
    expect(api.calls()).toBe(2);

    const off = fakeApi(() => json({items: []}, {headers: {"cache-control": "max-age=60"}}), () => json({items: []}, {headers: {"cache-control": "max-age=60"}}));
    const uncached = new Heir({fetch: off.fetch, cache: false});
    await uncached.league("nacl").items();
    await uncached.league("nacl").items();
    expect(off.calls()).toBe(2);
  });

  it("keeps answers read with a key apart from answers read without one", async () => {
    const api = fakeApi(() => json({items: [1]}, {headers: {"cache-control": "max-age=60"}}), () => json({items: [2]}, {headers: {"cache-control": "max-age=60"}}));
    const anon = new Heir({fetch: api.fetch});
    const keyed = new Heir({fetch: api.fetch, apiKey: "k"});
    expect(await anon.league("nacl").items()).toEqual({items: [1]});
    expect(await keyed.league("nacl").items()).toEqual({items: [2]});
  });
});

describe("pagination", () => {
  const roster = (name: string) => ({id: name, name, tag: null, logoUrl: null, teamMmr: 1500, provisional: false, category: "competitive", captain: null});

  it("walks every page with the same filters, dropping page once a token continues the list", async () => {
    const api = fakeApi(
      () => json({rosters: [roster("a"), roster("b")], page: 0, pageSize: 2, hasMore: true, nextToken: "t1"}),
      () => json({rosters: [roster("c")], page: 1, pageSize: 2, hasMore: true, nextToken: "t2"}),
      () => json({rosters: [], page: 2, pageSize: 2, hasMore: false, nextToken: null})
    );
    const heir = new Heir({fetch: api.fetch});
    const first = await heir.league("nacl").rosters({category: "competitive", pageSize: 2, page: 0});
    expect(first.items.map(r => r.name)).toEqual(["a", "b"]);
    expect([first.hasMore, first.nextToken, first.body.page]).toEqual([true, "t1", 0]);
    const names: string[] = [];
    for await (const item of first) names.push(item.name);
    expect(names).toEqual(["a", "b", "c"]);
    expect(api.requests.map(r => new URL(r.url).search)).toEqual(["?category=competitive&pageSize=2&page=0", "?category=competitive&pageSize=2&nextToken=t1", "?category=competitive&pageSize=2&nextToken=t2"]);
    const last = await (await first.next())!.next();
    expect(last!.hasMore).toBe(false);
    expect(await last!.next()).toBeNull();
  });

  it("exposes the snapshot fields of leaderboards and standings on the page body", async () => {
    const api = fakeApi(() => json({metric: "mmr", category: "overall", entries: [{position: 1, displayName: "Ada", profileUrl: null, value: 1800, provisional: false}], page: 0, pageSize: 25, hasMore: false, nextToken: null, snapshotAt: "2026-10-29T10:00:00.000Z", snapshotExpiresAt: "2026-10-29T10:05:00.000Z"}));
    const page = await new Heir({fetch: api.fetch}).league("nacl").leaderboard({metric: "mmr"});
    expect(page.items[0]!.displayName).toBe("Ada");
    expect(page.body.snapshotAt).toBe("2026-10-29T10:00:00.000Z");
  });
});

describe("stat submission", () => {
  it("sends an Idempotency-Key on every tracking write, generated unless given, and the dryRun flag as a query", async () => {
    const api = fakeApi(() => json({matchId: "m1", created: true, approval: "automatic", replayed: false}), () => json({accepted: 1, duplicates: 0, dryRun: true}), () => json({closed: true, status: "approved", heldForReview: false, replayed: false}));
    const heir = new Heir({apiKey: "k", fetch: api.fetch});
    await heir.stats.beginMatch({matchId: "m1", startedAt: 1790000000000});
    await heir.stats.appendUnits("m1", {games: [{schemaRef: "mordhau.skirmish@1", gameId: "g1"}]}, {idempotencyKey: "g1-round-0", dryRun: true});
    await heir.stats.finalize("m1");
    const [begin, append, finalize] = api.requests;
    expect(begin!.headers.get("idempotency-key")).toMatch(/^[0-9a-f-]{36}$/);
    expect(append!.headers.get("idempotency-key")).toBe("g1-round-0");
    expect(append!.url).toBe("https://api.heir.gg/public/v1/stats/matches/m1/units?dryRun=true");
    expect(finalize!.url).toBe("https://api.heir.gg/public/v1/stats/matches/m1/finalize");
    expect(await finalize!.text()).toBe("{}");
    expect(finalize!.headers.get("content-type")).toBe("application/json");
  });

  it("retries a tracking write after a connection failure with the same key, so nothing is written twice", async () => {
    const api = fakeApi(() => { throw new TypeError("reset"); }, () => json({deadline: 1, replayed: false}));
    const heir = new Heir({apiKey: "k", fetch: api.fetch});
    vi.useFakeTimers();
    const pending = heir.stats.heartbeat("m1");
    await vi.runAllTimersAsync();
    await pending;
    expect(api.requests.map(r => r.headers.get("idempotency-key"))).toEqual([api.requests[0]!.headers.get("idempotency-key"), api.requests[0]!.headers.get("idempotency-key")]);
  });

  it("retries a complete-match submission that carries a reference", async () => {
    const api = fakeApi(() => { throw new TypeError("reset"); }, () => json({kind: "match", id: "9f6d2a70-0000-4000-8000-000000000000", status: "approved", created: true, replayed: false, problems: []}));
    const heir = new Heir({apiKey: "k", fetch: api.fetch});
    vi.useFakeTimers();
    const pending = heir.stats.submitMatch({format: "heir-match-v1", reference: "lobby-42", startedAt: "2026-10-16T19:00:00Z", maps: [{players: [{identity: "A1B2C3D4E5F67890", side: "a"}]}]});
    await vi.runAllTimersAsync();
    expect((await pending).created).toBe(true);
    expect(api.calls()).toBe(2);
  });
});

describe("package", () => {
  it("reports the version package.json carries", () => {
    const manifest = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")) as {version: string};
    expect(VERSION).toBe(manifest.version);
  });
});
