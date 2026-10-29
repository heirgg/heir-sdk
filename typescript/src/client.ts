import {Http, type HeirOptions} from "./http.js";
import {League} from "./league.js";
import {Stats} from "./stats.js";

/**
 * The Heir API client.
 *
 * ```ts
 * import {Heir} from "@heir/sdk";
 *
 * const heir = new Heir({apiKey: process.env.HEIR_API_KEY});
 * const nacl = heir.league("nacl");
 * const {player} = await nacl.player("mordhau", "A1B2C3D4E5F67890");
 * for await (const roster of await nacl.rosters()) console.log(roster.name, roster.teamMmr);
 * ```
 *
 * Reads work without a key. Eligibility checks and stat submission need the League's developer key.
 */
export class Heir {
  /** Stat submission for the key's League. */
  readonly stats: Stats;
  private readonly http: Http;
  private readonly leagues = new Map<string, League>();

  constructor(options: HeirOptions = {}) {
    this.http = new Http(options);
    this.stats = new Stats(this.http);
  }

  /** A League's public reads, by vanity name (`heir.gg/nacl`) or Discord server ID. */
  league(ref: string): League {
    let league = this.leagues.get(ref);
    if (!league) {
      league = new League(this.http, ref);
      this.leagues.set(ref, league);
    }
    return league;
  }

  /** Whether this client sends a developer key. */
  get authenticated(): boolean {
    return this.http.authenticated;
  }

  /** Forget every cached League read. */
  clearCache(): void {
    this.http.clearCache();
  }
}
