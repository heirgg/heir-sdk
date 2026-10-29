import {HeirApiError, HeirConnectionError, HeirTimeoutError} from "./errors.js";
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
  /** Extra headers for this call. */
  headers?: Record<string, string> | undefined;
  maxRetries?: number | undefined;
  timeoutMs?: number | undefined;
  /** false to ask the API even when a fresh cached answer exists. */
  cache?: boolean | undefined;
}

export type Query = Record<string, string | number | boolean | null | undefined>;

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
  etag: string | null;
  body: unknown;
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
    this.apiKey = options.apiKey?.trim() || undefined;
    this.baseUrl = (options.baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
    const fetchImpl = options.fetch ?? globalThis.fetch;
    if (typeof fetchImpl !== "function") throw new HeirConnectionError("No fetch is available in this runtime. Pass one in the `fetch` option.");
    this.fetch = fetchImpl;
    this.maxRetries = options.maxRetries ?? 2;
    this.maxRetryDelayMs = options.maxRetryDelayMs ?? 30_000;
    this.timeoutMs = options.timeoutMs ?? 30_000;
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
    const url = this.url(call.path, call.query);
    const useCache = call.cacheable && this.cacheEnabled && options.cache !== false;
    const cacheKey = `${this.apiKey ? "key" : "anon"} ${url}`;
    const cached = useCache ? this.cache.get(cacheKey) : undefined;
    if (cached && cached.freshUntil > Date.now()) return cached.body as T;

    const headers = new Headers(options.headers);
    headers.set("Accept", "application/json");
    if (call.body !== undefined) headers.set("Content-Type", "application/json");
    if (this.apiKey) headers.set("Authorization", `Bearer ${this.apiKey}`);
    if (call.idempotencyKey) headers.set("Idempotency-Key", call.idempotencyKey);
    if (cached?.etag) headers.set("If-None-Match", cached.etag);
    headers.set("User-Agent", this.userAgent);
    const body = call.body === undefined ? undefined : JSON.stringify(call.body);
    const maxRetries = options.maxRetries ?? this.maxRetries;

    for (let attempt = 0; ; attempt++) {
      let response: Response;
      try {
        response = await this.send(url, {method: call.method, headers, body}, options);
      } catch (error) {
        if (error instanceof HeirConnectionError && !(error instanceof HeirTimeoutError) && call.idempotent && attempt < maxRetries) {
          await sleep(backoff(attempt));
          continue;
        }
        throw error;
      }
      if (response.status === 304 && cached) {
        this.cache.set(cacheKey, {...cached, freshUntil: freshUntil(response.headers)});
        return cached.body as T;
      }
      if (response.ok) {
        const data: unknown = response.status === 204 ? undefined : await response.json();
        if (useCache) this.store(cacheKey, response.headers, data);
        return data as T;
      }
      const failure = await HeirApiError.from(response);
      const retryable = RETRY_STATUSES.has(failure.status) || (call.idempotent && RETRY_STATUSES_IF_IDEMPOTENT.has(failure.status));
      if (retryable && attempt < maxRetries) {
        const delay = failure.retryAfter !== undefined ? failure.retryAfter * 1000 : backoff(attempt);
        if (delay <= this.maxRetryDelayMs) {
          await sleep(delay);
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

  private store(key: string, headers: Headers, body: unknown): void {
    const control = headers.get("cache-control") ?? "";
    if (/\bno-store\b/i.test(control)) return;
    const etag = headers.get("etag");
    const until = freshUntil(headers);
    if (!etag && until === 0) return;
    if (this.cache.size >= MAX_CACHE_ENTRIES) {
      const oldest = this.cache.keys().next().value;
      if (oldest !== undefined) this.cache.delete(oldest);
    }
    this.cache.delete(key);
    this.cache.set(key, {etag, body, freshUntil: until});
  }

  private async send(url: string, init: {method: string; headers: Headers; body: string | undefined}, options: RequestOptions): Promise<Response> {
    const timeoutMs = options.timeoutMs ?? this.timeoutMs;
    const controller = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
    unref(timer);
    const onAbort = () => controller.abort(options.signal?.reason);
    if (options.signal?.aborted) onAbort();
    else options.signal?.addEventListener("abort", onAbort, {once: true});
    try {
      return await this.fetch(url, {method: init.method, headers: init.headers, signal: controller.signal, ...(init.body !== undefined ? {body: init.body} : {})});
    } catch (error) {
      if (timedOut) throw new HeirTimeoutError(timeoutMs, url);
      if (options.signal?.aborted) throw error;
      throw new HeirConnectionError(`Could not reach ${url}: ${error instanceof Error ? error.message : String(error)}`, error);
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener("abort", onAbort);
    }
  }
}

/** When an answer stops being fresh, from its `Cache-Control: max-age`; 0 when it has none and must be revalidated. */
const freshUntil = (headers: Headers): number => {
  const match = /\bmax-age=(\d+)/i.exec(headers.get("cache-control") ?? "");
  return match ? Date.now() + Number(match[1]) * 1000 : 0;
};

/** 500 ms, 1 s, 2 s, ... with jitter, capped at 8 s. */
const backoff = (attempt: number): number => Math.min(8000, 500 * 2 ** attempt) * (0.75 + Math.random() * 0.5);

const sleep = (ms: number): Promise<void> => new Promise(resolve => {
  const timer = setTimeout(resolve, ms);
  unref(timer);
});

/** A timer must not keep a Node process alive on its own. Browsers have no such thing. */
const unref = (timer: ReturnType<typeof setTimeout>): void => {
  (timer as unknown as {unref?: () => void}).unref?.();
};
