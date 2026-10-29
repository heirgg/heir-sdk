import type {Http, RequestOptions} from "./http.js";
import {Page} from "./pagination.js";
import type {
  EligibilityRequest, EligibilityResponse, Fixture, FixtureResponse, FixturesQuery, FixturesResponse, InventoryBatchRequest, InventoryBatchResponse, InventoryQuery,
  InventoryResponse, LeaderboardEntry, LeaderboardQuery, LeaderboardResponse, LeagueConfigResponse, LeagueItemsResponse, MatchResponse, PlayerLookupRequest, PlayerLookupResponse,
  PlayerMatch, PlayerMatchesQuery, PlayerMatchesResponse, PlayerQuery, PlayerResponse, PlayerStatsResponse, Roster, RosterQuery, RosterResponse, RostersQuery, RostersResponse,
  Standing, StandingsQuery, StandingsResponse
} from "./types.js";

const segment = (value: string): string => encodeURIComponent(value);

/**
 * One League's public reads: players, ratings, Rosters, schedules, results and shop inventory. Reads need no key and
 * are cached for a minute as the API asks; with the League's own developer key they draw on the plan's allowance
 * instead of the per-address limit. Get one from `heir.league("nacl")`, by vanity name or Discord server ID.
 */
export class League {
  private readonly base: string;

  constructor(private readonly http: Http, readonly ref: string) {
    this.base = `/public/v1/leagues/${segment(ref)}`;
  }

  /** One current Member by linked game account, for nameplates and player cards. `player` is null for an unknown or departed identity. */
  player(credential: string, identifier: string, query: PlayerQuery = {}, options?: RequestOptions): Promise<PlayerResponse> {
    return this.get(`/players/${segment(credential)}/${segment(identifier)}`, query, options);
  }

  /** Up to 100 game accounts at once, each answered in order, including duplicates and unavailable identities. */
  lookupPlayers(request: PlayerLookupRequest, options?: RequestOptions): Promise<PlayerLookupResponse> {
    return this.post("/players/lookup", request, options);
  }

  /** The Player's League win/loss record and stored performance totals for the scope. */
  playerStats(credential: string, identifier: string, query: PlayerQuery = {}, options?: RequestOptions): Promise<PlayerStatsResponse> {
    return this.get(`/players/${segment(credential)}/${segment(identifier)}/stats`, query, options);
  }

  /** The Player's rated results and MMR changes, newest first. */
  playerMatches(credential: string, identifier: string, query: PlayerMatchesQuery = {}, options?: RequestOptions): Promise<Page<PlayerMatch, PlayerMatchesResponse>> {
    return this.page(`/players/${segment(credential)}/${segment(identifier)}/matches`, query, body => body.matches, next => this.playerMatches(credential, identifier, next, options), options);
  }

  /** Active Rosters with their Team tags, logos, captain and Team MMR. */
  rosters(query: RostersQuery = {}, options?: RequestOptions): Promise<Page<Roster, RostersResponse>> {
    return this.page("/rosters", query, body => body.rosters, next => this.rosters(next, options), options);
  }

  /** One active Roster and its seated Members. */
  roster(id: string, query: RosterQuery = {}, options?: RequestOptions): Promise<RosterResponse> {
    return this.get(`/rosters/${segment(id)}`, query, options);
  }

  /** Current Members ordered by MMR, Heir Rating, wins or losses. A five-minute snapshot; `body.snapshotAt` says which. */
  leaderboard(query: LeaderboardQuery = {}, options?: RequestOptions): Promise<Page<LeaderboardEntry, LeaderboardResponse>> {
    return this.page("/leaderboards", query, body => body.entries, next => this.leaderboard(next, options), options);
  }

  /** Current-season Roster standings in competition order. */
  standings(query: StandingsQuery = {}, options?: RequestOptions): Promise<Page<Standing, StandingsResponse>> {
    return this.page("/standings", query, body => body.standings, next => this.standings(next, options), options);
  }

  /** Fixtures in scheduled-time order: scheduled by default, or played or cancelled with `status`. */
  fixtures(query: FixturesQuery = {}, options?: RequestOptions): Promise<Page<Fixture, FixturesResponse>> {
    return this.page("/fixtures", query, body => body.fixtures, next => this.fixtures(next, options), options);
  }

  /** One fixture: its Rosters, time, status, stream link and recorded result. */
  fixture(id: string, options?: RequestOptions): Promise<FixtureResponse> {
    return this.get(`/fixtures/${segment(id)}`, {}, options);
  }

  /** An official result or approved recording by UUID. */
  match(id: string, options?: RequestOptions): Promise<MatchResponse> {
    return this.get(`/matches/${segment(id)}`, {}, options);
  }

  /** Game credentials, active gamemodes, rating categories, rank definitions and batch limits. */
  config(options?: RequestOptions): Promise<LeagueConfigResponse> {
    return this.get("/config", {}, options);
  }

  /**
   * Check up to 100 game accounts against a fixture and one of its Rosters. Requires the League's developer key with
   * the gamemode granted. Advisory: it reserves no seats. Call it from your server.
   */
  checkEligibility(request: EligibilityRequest, options?: RequestOptions): Promise<EligibilityResponse> {
    return this.post("/eligibility/check", request, options);
  }

  /** The items one game account's owner holds in the League's shop right now. An empty list is a normal answer. */
  inventory(credential: string, identifier: string, query: InventoryQuery = {}, options?: RequestOptions): Promise<InventoryResponse> {
    return this.get(`/inventory/${segment(credential)}/${segment(identifier)}`, query, options);
  }

  /** The same for up to 100 game accounts at once, such as everyone on a server. Not cached. */
  inventories(credential: string, request: InventoryBatchRequest, options?: RequestOptions): Promise<InventoryBatchResponse> {
    return this.post(`/inventory/${segment(credential)}`, request, options);
  }

  /** Every item the League's shop knows, and the kinds of game account its inventory calls accept. */
  items(options?: RequestOptions): Promise<LeagueItemsResponse> {
    return this.get("/items", {}, options);
  }

  private get<T>(path: string, query: Record<string, string | number | undefined>, options?: RequestOptions): Promise<T> {
    return this.http.request<T>({method: "GET", path: this.base + path, query, idempotent: true, cacheable: true}, options);
  }

  private post<T>(path: string, body: unknown, options?: RequestOptions): Promise<T> {
    // These POSTs read and never write, so they are safe to send again; their answers are not cached by the API.
    return this.http.request<T>({method: "POST", path: this.base + path, body, idempotent: true, cacheable: false}, options);
  }

  private async page<Item, Body extends {page: number; pageSize: number; hasMore: boolean; nextToken: string | null}, Q extends {page?: number; pageSize?: number; nextToken?: string}>(
    path: string, query: Q, items: (body: Body) => readonly Item[], fetchNext: (query: Q) => Promise<Page<Item, Body>>, options?: RequestOptions
  ): Promise<Page<Item, Body>> {
    const body = await this.get<Body>(path, query as Record<string, string | number | undefined>, options);
    // A continuation keeps the filters and page size; `page` cannot be combined with a token.
    return new Page(body, items(body), nextToken => {
      const {page: _page, ...rest} = query;
      return fetchNext({...rest, nextToken} as Q);
    });
  }
}
