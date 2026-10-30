import {readFileSync} from "node:fs";
import {describe, expect, it} from "vitest";
import {Heir, Page, type PublicOperations, type StatOperations} from "../src/index.js";

type Operation = keyof PublicOperations | keyof StatOperations;
interface ContractCase {operationId: Operation; method: string; path: string; requestBody?: unknown; responseBody: unknown}
const cases = (JSON.parse(readFileSync(new URL("../../tests/contracts.json", import.meta.url), "utf8")) as {cases: ContractCase[]}).cases;
const id = "9f6d2a70-0000-4000-8000-000000000000";
const identity = "A1B2C3D4E5F67890";

// The root check verifies fixture operation/method/path coverage. These calls exercise the public wrappers.
const calls = (client: Heir, body: never): Record<Operation, () => Promise<unknown>> => {
  const league = client.league("nacl");
  return {
    getLeaguePlayer: () => league.player("mordhau", identity),
    lookupLeaguePlayers: () => league.lookupPlayers(body),
    getLeaguePlayerStats: () => league.playerStats("mordhau", identity),
    getLeaguePlayerMatches: () => league.playerMatches("mordhau", identity),
    listLeagueRosters: () => league.rosters(),
    getLeagueRoster: () => league.roster(id),
    getLeagueLeaderboard: () => league.leaderboard(),
    getLeagueStandings: () => league.standings(),
    listLeagueFixtures: () => league.fixtures(),
    getLeagueFixture: () => league.fixture(id),
    getLeagueMatch: () => league.match(id),
    getLeagueConfig: () => league.config(),
    checkLeagueEligibility: () => league.checkEligibility(body),
    getPlayerInventory: () => league.inventory("mordhau", identity),
    getPlayersInventory: () => league.inventories("mordhau", body),
    getLeagueItems: () => league.items(),
    submitCompleteMatch: () => client.stats.submitMatch(body),
    listGamemodes: () => client.stats.gamemodes(),
    listStatSchemas: () => client.stats.schemas(),
    beginMatch: () => client.stats.beginMatch(body),
    appendUnits: () => client.stats.appendUnits(id, body),
    heartbeatMatch: () => client.stats.heartbeat(id),
    finalizeMatch: () => client.stats.finalize(id),
    uploadMatch: () => client.stats.upload(body)
  };
};

describe("shared endpoint contracts", () => {
  it("includes every generated operation exactly once", () => {
    expect(cases.map(test => test.operationId).sort()).toEqual(Object.keys(calls(new Heir(), undefined as never)).sort());
  });

  it.each(cases)("$operationId", async test => {
    const client = new Heir({apiKey: "test-key", maxRetries: 0, fetch: async (url, init) => {
      expect(String(url)).toBe(`https://api.heir.gg${test.path}`);
      expect(init?.method).toBe(test.method);
      const headers = new Headers(init?.headers);
      expect(headers.get("authorization")).toBe("Bearer test-key");
      expect(headers.get("accept")).toBe("application/json");
      if (test.method === "POST") {
        expect(headers.get("content-type")).toBe("application/json");
        expect(JSON.parse(String(init?.body))).toEqual(test.requestBody);
      } else expect(init?.body).toBeUndefined();
      if (["beginMatch", "appendUnits", "heartbeatMatch", "finalizeMatch", "uploadMatch"].includes(test.operationId)) {
        expect(headers.get("idempotency-key")).toMatch(/^[0-9a-f-]{36}$/);
      }
      return new Response(JSON.stringify(test.responseBody), {headers: {"content-type": "application/json"}});
    }});
    const answer = await calls(client, test.requestBody as never)[test.operationId]();
    expect(answer instanceof Page ? answer.body : answer).toEqual(test.responseBody);
  });
});
