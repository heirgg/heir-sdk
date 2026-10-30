import {segment, type Http, type RequestOptions} from "./http.js";
import {HeirInputError} from "./errors.js";
import type {
  AppendUnitsRequest, AppendUnitsResponse, BeginMatchRequest, BeginMatchResponse, FinalizeMatchResponse, GamemodeCatalog, HeartbeatMatchResponse, HeirMatchFile, MatchEntryReceipt,
  StatSchemaCatalog, UploadMatchRequest, UploadMatchResponse
} from "./types.js";

/** Options a stat tracking write takes besides the usual ones. */
export interface WriteOptions extends RequestOptions {
  /**
   * Your own value unique to this request. The SDK generates one per call, so its own retries never write twice; set
   * it yourself when your code may send the same request again later, so the API answers as it did the first time.
   */
  idempotencyKey?: string | undefined;
  /** Check the request without storing anything: the answer says what would have happened. */
  dryRun?: boolean | undefined;
}

const STATS = "/public/v1/stats";

/**
 * Stat submission: send your game's stats to a League, for any gamemode it plays. Every call needs an API key with
 * the gamemode granted. Available while the League's stat submission API is switched on; otherwise the API answers
 * 503 `not-available`.
 */
export class Stats {
  constructor(private readonly http: Http) {}

  /** The gamemodes this key may submit, built-in and custom, each with the stat keys a Player line may carry and an empty `heir-match-v1` document to fill in. */
  gamemodes(options?: RequestOptions): Promise<GamemodeCatalog> {
    return this.http.request({method: "GET", path: `${STATS}/gamemodes`, idempotent: true, cacheable: false}, options);
  }

  /** The gamemode schemas this key may track a match under, with every counter and what one unit is, and the key's allowances. */
  schemas(options?: RequestOptions): Promise<StatSchemaCatalog> {
    return this.http.request({method: "GET", path: `${STATS}/schemas`, idempotent: true, cacheable: false}, options);
  }

  /**
   * One finished match as a `heir-match-v1` document, for any gamemode. Set `reference` to your own id for the match:
   * a repeat with the same contents is a no-op, and the SDK may then safely send it again after a connection failure.
   */
  submitMatch(file: HeirMatchFile, options?: RequestOptions): Promise<MatchEntryReceipt> {
    return this.http.request({method: "POST", path: `${STATS}/matches/complete`, body: file, idempotent: file.reference !== undefined, cacheable: false}, options);
  }

  /** Open a live match. It takes one of the League's live sessions until finalized or silent for 30 minutes. Beginning it again returns it. */
  beginMatch(request: BeginMatchRequest, options?: WriteOptions): Promise<BeginMatchResponse> {
    return this.write(`${STATS}/matches`, request, options);
  }

  /** Add rounds (or a whole game, for a gamemode without rounds) to an open match. The request is accepted or refused whole. */
  appendUnits(matchId: string, request: AppendUnitsRequest, options?: WriteOptions): Promise<AppendUnitsResponse> {
    return this.write(`${STATS}/matches/${segment(matchId)}/units`, request, options);
  }

  /** Say the match is still being played when no unit is ready; a match silent for 30 minutes is closed and held for review. */
  heartbeat(matchId: string, options?: WriteOptions): Promise<HeartbeatMatchResponse> {
    return this.write(`${STATS}/matches/${segment(matchId)}/heartbeat`, undefined, options);
  }

  /** Close the match and free its live session. A game without its result, or a missing round, holds it for an Organizer's review. */
  finalize(matchId: string, options?: WriteOptions): Promise<FinalizeMatchResponse> {
    return this.write(`${STATS}/matches/${segment(matchId)}/finalize`, undefined, options);
  }

  /** A complete tracked match in one request. It never holds a live session; the same upload again changes nothing. */
  upload(request: UploadMatchRequest, options?: WriteOptions): Promise<UploadMatchResponse> {
    return this.write(`${STATS}/uploads`, request, options);
  }

  private write<T>(path: string, body: unknown, options: WriteOptions = {}): Promise<T> {
    const {idempotencyKey, dryRun, ...rest} = options;
    return this.http.request<T>({
      method: "POST", path, body: body ?? {}, idempotent: true, cacheable: false,
      idempotencyKey: idempotencyKey ?? newIdempotencyKey(),
      ...(dryRun ? {query: {dryRun: "true"}} : {})
    }, rest);
  }
}

/** A fresh idempotency key: a UUID. */
export const newIdempotencyKey = (): string => {
  if (typeof globalThis.crypto?.randomUUID !== "function") throw new HeirInputError("This runtime requires crypto.randomUUID(), or an explicit idempotencyKey for tracking writes.");
  return globalThis.crypto.randomUUID();
};
