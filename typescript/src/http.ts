import {HeirApiError, HeirConnectionError, HeirInputError, HeirProtocolError, HeirTimeoutError} from "./errors.js";
import {VERSION} from "./version.js";

export const DEFAULT_BASE_URL = "https://api.heir.gg";

export interface HeirOptions {
  /**
   * A League developer key, from Manage League, Developer, API keys. Leave it out to read League data without one
   * (120 requests a minute per address). Call from your server: never put a key in a game client or browser.
   */
  apiKey?: string | undefined;
  /** Where the API is. The default is the production API. */
  baseUrl?: string | undefined;
  /** The fetch to use. The default is the runtime's own; pass one to add a proxy, an agent or a fake for tests. */
  fetch?: typeof globalThis.fetch | undefined;
  /**
   * How many times a request is sent again after a 429, a 503, or (for a read or a write with an Idempotency-Key) a
   * connection failure or gateway error, waiting as `Retry-After` says or with increasing backoff. Default 2.
   */
  maxRetries?: number | undefined;
  /** The longest the SDK waits before one retry. A `Retry-After` beyond it is not waited for: the error is thrown with `retryAfter` set. Default 30 000. */
  maxRetryDelayMs?: number | undefined;
  /** How long one attempt may take before it is abandoned with a HeirTimeoutError. Default 30 000. */
  timeoutMs?: number | undefined;
  /**
   * Keep League reads as the API's `Cache-Control` allows (a minute) and revalidate them with `ETag`, so a server
   * asking on every event does not spend its request allowance. Default true. Paginated and stat answers are never
   * cached: the API marks them `no-store`.
   */
  cache?: boolean | undefined;
  /** Added to the User-Agent, to say which integration is calling. */
  userAgent?: string | undefined;
}

/** Options one call may take. */
export interface RequestOptions {
  /** Abort the call. A timed-out call throws HeirTimeoutError; an aborted one rethrows the signal's reason. */
  signal?: AbortSignal | undefined;
  /** Extra headers for this call. Bypasses caching. SDK-controlled headers take precedence. */
  headers?: Record<string, string> | undefined;
  maxRetries?: number | undefined;
  timeoutMs?: number | undefined;
  /** false to ask the API even when a fresh cached answer exists. */
  cache?: boolean | undefined;
}

export type Query = Record<string, string | number | boolean | null | undefined>;

/** Encode one path segment without allowing dot-segment URL normalization. */
export const segment = (value: string): string => {
  if (typeof value !== "string" || !value || value === "." || value === "..") throw new HeirInputError("Path parameters must be nonempty strings other than '.' or '..'.");
  try { return encodeURIComponent(value); }
  catch (cause) { throw new HeirInputError("Path parameters must contain valid Unicode.", {cause}); }
};

/** One API call as the resources describe it to the transport. */
export interface Call {
  method: "GET" | "POST";
  /** The path with its parameters already encoded, such as `/public/v1/leagues/nacl/rosters`. */
  path: string;
  query?: Query | undefined;
  body?: unknown;
  /** Safe to send again after a connection failure or gateway error: every read, and a write carrying an Idempotency-Key. */
  idempotent: boolean;
  /** A read whose answer may be kept as its Cache-Control says. */
  cacheable: boolean;
  idempotencyKey?: string | undefined;
}

interface CacheEntry {
  headers: Headers;
  body: string;
  /** When the entry stops being served without asking the API, as a timestamp; 0 when it must always be revalidated. */
  freshUntil: number;
}

const MAX_CACHE_ENTRIES = 1000;
const RETRY_STATUSES = new Set([429, 503]);
const RETRY_STATUSES_IF_IDEMPOTENT = new Set([500, 502, 504]);

/** The transport every resource shares: URL building, authentication, retries, caching and timeouts. */
export class Http {
  private readonly apiKey: string | undefined;
  private readonly baseUrl: string;
  private readonly fetch: typeof globalThis.fetch;
  private readonly maxRetries: number;
  private readonly maxRetryDelayMs: number;
  private readonly timeoutMs: number;
  private readonly cacheEnabled: boolean;
  private readonly userAgent: string;
  private readonly cache = new Map<string, CacheEntry>();

  constructor(options: HeirOptions = {}) {
    if (options.apiKey !== undefined && typeof options.apiKey !== "string") throw new HeirInputError("apiKey must be a string.");
    if (options.userAgent !== undefined && typeof options.userAgent !== "string") throw new HeirInputError("userAgent must be a string.");
    if (options.cache !== undefined && typeof options.cache !== "boolean") throw new HeirInputError("cache must be a boolean.");
    if (options.fetch !== undefined && typeof options.fetch !== "function") throw new HeirInputError("fetch must be a function.");
    this.apiKey = options.apiKey?.trim() || undefined;
    this.baseUrl = baseUrl(options.baseUrl ?? DEFAULT_BASE_URL);
    const fetchImpl = options.fetch ?? globalThis.fetch;
    if (typeof fetchImpl !== "function") throw new HeirConnectionError("No fetch is available in this runtime. Pass one in the `fetch` option.");
    this.fetch = fetchImpl;
    this.maxRetries = nonnegative("maxRetries", options.maxRetries ?? 2, true);
    this.maxRetryDelayMs = nonnegative("maxRetryDelayMs", options.maxRetryDelayMs ?? 30_000);
    if (this.maxRetryDelayMs > 2_147_483_647) throw new HeirInputError("maxRetryDelayMs must not exceed 2147483647 milliseconds.");
    this.timeoutMs = timeout(options.timeoutMs ?? 30_000);
    this.cacheEnabled = options.cache ?? true;
    this.userAgent = `heir-sdk-typescript/${VERSION}${options.userAgent ? ` ${options.userAgent}` : ""}`;
  }

  /** Whether calls carry a developer key. */
  get authenticated(): boolean {
    return this.apiKey !== undefined;
  }

  url(path: string, query?: Query): string {
    const url = new URL(this.baseUrl + path);
    for (const [name, value] of Object.entries(query ?? {})) if (value !== undefined && value !== null) url.searchParams.set(name, String(value));
    return url.toString();
  }

  async request<T>(call: Call, options: RequestOptions = {}): Promise<T> {
    options = {...options, ...(options.headers ? {headers: {...options.headers}} : {})};
    options.signal?.throwIfAborted();
    if (options.cache !== undefined && typeof options.cache !== "boolean") throw new HeirInputError("cache must be a boolean.");
    const maxRetries = nonnegative("maxRetries", options.maxRetries ?? this.maxRetries, true);
    const timeoutMs = timeout(options.timeoutMs ?? this.timeoutMs);
    const url = this.url(call.path, call.query);
    const useCache = call.cacheable && this.cacheEnabled && options.cache !== false && Object.keys(options.headers ?? {}).length === 0;
    const cacheKey = `${this.apiKey ? "key" : "anon"} ${url}`;
    const cached = useCache ? this.cache.get(cacheKey) : undefined;
    if (cached && cached.freshUntil > Date.now()) return parseBody<T>(cached.body, 200);

    let headers: Headers;
    let body: string | undefined;
    try {
      headers = new Headers(options.headers);
      headers.set("Accept", "application/json");
      if (call.body !== undefined) headers.set("Content-Type", "application/json");
      if (this.apiKey) headers.set("Authorization", `Bearer ${this.apiKey}`);
      if (call.idempotencyKey !== undefined) {
        if (!call.idempotencyKey.trim()) throw new Error("idempotencyKey must not be empty.");
        headers.set("Idempotency-Key", call.idempotencyKey);
      }
      const etag = cached?.headers.get("etag");
      if (etag) headers.set("If-None-Match", etag);
      headers.set("User-Agent", this.userAgent);
      body = call.body === undefined ? undefined : JSON.stringify(call.body);
      if (call.body !== undefined && body === undefined) throw new Error("The request body cannot be encoded as JSON.");
    } catch (cause) {
      throw new HeirInputError("Could not encode request body or headers.", {cause});
    }

    for (let attempt = 0; ; attempt++) {
      options.signal?.throwIfAborted();
      let response: Response;
      let text: string;
      try {
        ({response, text} = await this.send(url, {method: call.method, headers, body}, {...options, timeoutMs}));
      } catch (error) {
        if (error instanceof HeirConnectionError && !(error instanceof HeirTimeoutError) && call.idempotent && attempt < maxRetries) {
          const delay = backoff(attempt);
          if (delay <= this.maxRetryDelayMs) {
            await sleep(delay, options.signal);
            continue;
          }
        }
        throw error;
      }
      if (response.status === 304 && cached) {
        const merged = new Headers(cached.headers);
        // Age and Date describe this validation response, not the earlier response.
        merged.delete("age"); merged.delete("date");
        response.headers.forEach((value, name) => merged.set(name, value));
        this.store(cacheKey, merged, cached.body);
        return parseBody<T>(cached.body, 200);
      }
      if (response.ok) {
        const data = parseBody<T>(text, response.status);
        if (useCache) this.store(cacheKey, response.headers, text);
        return data;
      }
      const failure = await HeirApiError.from(response, text);
      const retryable = RETRY_STATUSES.has(failure.status) || (call.idempotent && RETRY_STATUSES_IF_IDEMPOTENT.has(failure.status));
      if (retryable && attempt < maxRetries) {
        const delay = failure.retryAfter !== undefined ? failure.retryAfter * 1000 : backoff(attempt);
        if (delay <= this.maxRetryDelayMs) {
          await sleep(delay, options.signal);
          continue;
        }
      }
      throw failure;
    }
  }

  /** Forget every cached answer. */
  clearCache(): void {
    this.cache.clear();
  }

  private store(key: string, headers: Headers, body: string): void {
    this.cache.delete(key);
    const control = headers.get("cache-control") ?? "";
    // Conservatively bypass all response variations rather than risk mixing representations.
    if (/\bno-store\b/i.test(control) || headers.get("vary")?.trim()) return;
    const etag = headers.get("etag");
    const until = freshUntil(headers);
    if (!etag && until === 0) return;
    if (this.cache.size >= MAX_CACHE_ENTRIES) {
      const oldest = this.cache.keys().next().value;
      if (oldest !== undefined) this.cache.delete(oldest);
    }
    this.cache.set(key, {headers: new Headers(headers), body, freshUntil: until});
  }

  private async send(url: string, init: {method: string; headers: Headers; body: string | undefined}, options: RequestOptions): Promise<{response: Response; text: string}> {
    const timeoutMs = options.timeoutMs ?? this.timeoutMs;
    const controller = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
    const onAbort = () => controller.abort(options.signal?.reason);
    if (options.signal?.aborted) onAbort();
    else options.signal?.addEventListener("abort", onAbort, {once: true});
    try {
      const response = await this.fetch(url, {method: init.method, headers: init.headers, signal: controller.signal, ...(init.body !== undefined ? {body: init.body} : {})});
      const text = response.status === 204 || response.status === 304 ? "" : await response.text();
      controller.signal.throwIfAborted();
      return {response, text};
    } catch (error) {
      if (timedOut) throw new HeirTimeoutError(timeoutMs, url);
      if (options.signal?.aborted) throw options.signal.reason;
      throw new HeirConnectionError(`Could not reach ${url}: ${error instanceof Error ? error.message : String(error)}`, error);
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener("abort", onAbort);
    }
  }
}

/** When an answer stops being fresh, from its `Cache-Control: max-age`; 0 when it has none and must be revalidated. */
const freshUntil = (headers: Headers): number => {
  const control = headers.get("cache-control") ?? "";
  if (/\bno-cache\b/i.test(control)) return 0;
  const match = /(?:^|,)\s*max-age\s*=\s*"?(\d+)"?/i.exec(control);
  if (!match) return 0;
  const now = Date.now();
  const date = Date.parse(headers.get("date") ?? "");
  const age = Number(headers.get("age") ?? 0);
  const apparentAge = Number.isFinite(date) ? Math.max(0, now - date) : 0;
  const ageMs = Number.isFinite(age) ? Math.max(0, age) * 1000 : 0;
  return now + Math.max(0, Number(match[1]) * 1000 - Math.max(apparentAge, ageMs));
};

/** 500 ms, 1 s, 2 s, ... with jitter, capped at 8 s. */
const backoff = (attempt: number): number => Math.min(8000, 500 * 2 ** attempt * (0.75 + Math.random() * 0.5));

const sleep = (ms: number, signal?: AbortSignal): Promise<void> => new Promise((resolve, reject) => {
  signal?.throwIfAborted();
  const timer = setTimeout(() => { signal?.removeEventListener("abort", onAbort); resolve(); }, ms);
  const onAbort = () => { clearTimeout(timer); reject(signal?.reason); };
  signal?.addEventListener("abort", onAbort, {once: true});
});

const nonnegative = (name: string, value: number, integer = false): number => {
  if (!Number.isFinite(value) || value < 0 || (integer && !Number.isSafeInteger(value))) throw new HeirInputError(`${name} must be a finite, nonnegative ${integer ? "integer" : "number"}.`);
  return value;
};

const timeout = (value: number): number => {
  if (!Number.isFinite(value) || value <= 0 || value > 2_147_483_647) throw new HeirInputError("timeoutMs must be positive and at most 2147483647 milliseconds.");
  return value;
};

const baseUrl = (value: string): string => {
  try {
    if (typeof value !== "string" || value.includes("?") || value.includes("#")) throw new Error("Expected a URL without query or fragment delimiters.");
    const url = new URL(value);
    if (!["https:", "http:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error("Expected an HTTP(S) URL without credentials, query, or fragment.");
    return url.toString().replace(/\/+$/, "");
  } catch (cause) { throw new HeirInputError("baseUrl must be an HTTP(S) API URL without credentials, query, or fragment.", {cause}); }
};

const parseBody = <T>(text: string, status: number): T => {
  let data: unknown;
  try { data = JSON.parse(text); }
  catch (cause) { throw new HeirProtocolError("The API returned invalid JSON.", status, cause); }
  if (typeof data !== "object" || data === null || Array.isArray(data)) throw new HeirProtocolError("The API returned JSON that is not an object.", status);
  return data as T;
};
