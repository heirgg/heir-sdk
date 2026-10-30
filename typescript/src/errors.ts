/** SDK errors extend HeirError. Caller-initiated cancellation preserves the caller's reason. */
export class HeirError extends Error {
  override readonly name: string = "HeirError";
}

/** Invalid SDK configuration or a request that cannot be encoded. */
export class HeirInputError extends HeirError {
  override readonly name = "HeirInputError";
}

/** A successful HTTP response that is not a JSON object. */
export class HeirProtocolError extends HeirError {
  override readonly name = "HeirProtocolError";

  constructor(message: string, readonly status: number, cause?: unknown) {
    super(message, {cause});
  }
}

/** One field the API could not accept, named when it can be. */
export interface ApiIssue {
  path: string;
  message: string;
}

/**
 * The API answered with an error. `code` is the stable code to branch on (`rate-limited`, `league-not-found`,
 * `rejected`, ...), `message` a sentence for a person whose wording can change. `status` is the HTTP status and
 * `retryAfter`, on a 429, how many seconds the API asked you to wait.
 */
export class HeirApiError extends HeirError {
  override readonly name = "HeirApiError";
  readonly status: number;
  readonly code: string;
  readonly issues: readonly ApiIssue[] | undefined;
  readonly retryAfter: number | undefined;
  readonly headers: Headers;
  readonly body: unknown;

  constructor(init: {status: number; code: string; message: string; issues?: readonly ApiIssue[] | undefined; retryAfter?: number | undefined; headers: Headers; body: unknown}) {
    super(init.message);
    this.status = init.status;
    this.code = init.code;
    this.issues = init.issues;
    this.retryAfter = init.retryAfter;
    this.headers = init.headers;
    this.body = init.body;
  }

  /** Too many requests this minute, or the League has as many live sessions open as its plan allows. */
  get isRateLimited(): boolean {
    return this.status === 429;
  }

  /** Reads the API's `{error, message, issues?}` envelope; an answer that is not one still becomes an error you can inspect. */
  static async from(response: Response, text?: string): Promise<HeirApiError> {
    text ??= await response.text();
    let body: unknown = text;
    try { body = text ? JSON.parse(text) : undefined; } catch { /* not JSON: keep the text */ }
    const envelope = isEnvelope(body) ? body : undefined;
    return new HeirApiError({
      status: response.status,
      code: envelope?.error ?? "unknown",
      message: envelope?.message ?? `The API answered ${response.status}${response.statusText ? ` ${response.statusText}` : ""}.`,
      issues: Array.isArray(envelope?.issues) ? envelope.issues.filter(isIssue) : undefined,
      retryAfter: parseRetryAfter(response.headers.get("retry-after")),
      headers: response.headers,
      body
    });
  }
}

/** The API could not be reached, or the connection failed before an answer arrived. `cause` is the underlying error. */
export class HeirConnectionError extends HeirError {
  override readonly name: string = "HeirConnectionError";
  override readonly cause: unknown;

  constructor(message: string, cause?: unknown) {
    super(message);
    this.cause = cause;
  }
}

/** No answer arrived within the request's timeout. */
export class HeirTimeoutError extends HeirConnectionError {
  override readonly name = "HeirTimeoutError";
  readonly timeoutMs: number;

  constructor(timeoutMs: number, url: string) {
    super(`No answer from ${url} within ${timeoutMs} ms.`);
    this.timeoutMs = timeoutMs;
  }
}

const isEnvelope = (value: unknown): value is {error: string; message: string; issues?: unknown} =>
  typeof value === "object" && value !== null && typeof (value as {error?: unknown}).error === "string" && typeof (value as {message?: unknown}).message === "string";

const isIssue = (value: unknown): value is ApiIssue => typeof value === "object" && value !== null &&
  typeof (value as ApiIssue).path === "string" && typeof (value as ApiIssue).message === "string";

/** `Retry-After` as seconds, from either form the header takes: a count of seconds or an HTTP date. */
export const parseRetryAfter = (header: string | null): number | undefined => {
  if (!header) return undefined;
  const seconds = Number(header);
  if (Number.isFinite(seconds)) return Math.max(0, seconds);
  const at = Date.parse(header);
  return Number.isNaN(at) ? undefined : Math.max(0, Math.ceil((at - Date.now()) / 1000));
};
