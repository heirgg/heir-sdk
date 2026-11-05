// Friendly names for the generated types. The generated modules are the whole truth; these are the parts a caller
// reaches for. Each request and response body is a component named by ../../spec/type-names.json; a shape inside one is
// named here by where it sits. Both documents define an `Error` component, exported here as PublicApiError and
// StatApiError so neither shadows the global Error.
import type {components as PublicComponents, operations as PublicOperations} from "./generated/public.js";
import type {components as StatComponents, operations as StatOperations} from "./generated/stats.js";

export type {paths as PublicPaths, operations as PublicOperations, components as PublicComponents} from "./generated/public.js";
export type {paths as StatPaths, operations as StatOperations, components as StatComponents} from "./generated/stats.js";

type PublicSchema<Name extends keyof PublicComponents["schemas"]> = PublicComponents["schemas"][Name];
type StatSchema<Name extends keyof StatComponents["schemas"]> = StatComponents["schemas"][Name];
type QueryOf<Op extends keyof PublicOperations> = NonNullable<PublicOperations[Op]["parameters"]["query"]>;

// League reads.
export type PlayerResponse = PublicSchema<"PlayerResponse">;
export type Player = NonNullable<PlayerResponse["player"]>;
export type Rank = NonNullable<Player["rank"]>;
export type PlayerLookupRequest = PublicSchema<"PlayerLookupRequest">;
export type PlayerLookupResponse = PublicSchema<"PlayerLookupResponse">;
export type PlayerLookupResult = PlayerLookupResponse["players"][number];
export type PlayerStatsResponse = PublicSchema<"PlayerStatsResponse">;
export type PlayerMatchesResponse = PublicSchema<"PlayerMatchesResponse">;
export type PlayerMatch = PlayerMatchesResponse["matches"][number];
export type RostersResponse = PublicSchema<"RostersResponse">;
export type RosterResponse = PublicSchema<"RosterResponse">;
export type Roster = RosterResponse["roster"];
export type RosterMember = RosterResponse["members"][number];
export type LeaderboardResponse = PublicSchema<"LeaderboardResponse">;
export type LeaderboardEntry = LeaderboardResponse["entries"][number];
export type StandingsResponse = PublicSchema<"StandingsResponse">;
export type Standing = StandingsResponse["standings"][number];
export type FixturesResponse = PublicSchema<"FixturesResponse">;
export type FixtureResponse = PublicSchema<"FixtureResponse">;
export type Fixture = FixtureResponse["fixture"];
export type MatchResponse = PublicSchema<"MatchResponse">;
export type Match = MatchResponse["match"];
export type LeagueConfigResponse = PublicSchema<"LeagueConfigResponse">;
/** Heir's mark on a League: `verified` or `official`. A League without one has no `recognition`, or null. */
export type LeagueRecognition = NonNullable<LeagueConfigResponse["recognition"]>;
export type EligibilityRequest = PublicSchema<"EligibilityRequest">;
export type EligibilityResponse = PublicSchema<"EligibilityResponse">;
export type EligibilityVerdict = EligibilityResponse["players"][number];
// Every League read answers an error in the same shape.
export type LeagueError = PublicOperations["getLeaguePlayer"]["responses"][400]["content"]["application/json"];
export type LeagueErrorCode = LeagueError["error"];

// Inventory.
export type Item = PublicSchema<"Item">;
export type InventoryResponse = PublicSchema<"InventoryResponse">;
export type InventoryBatchRequest = PublicSchema<"InventoryBatchRequest">;
export type InventoryBatchResponse = PublicSchema<"InventoryBatchResponse">;
export type LeagueItemsResponse = PublicSchema<"LeagueItemsResponse">;
export type LeagueItem = LeagueItemsResponse["items"][number];
export type LeagueCredential = LeagueItemsResponse["credentials"][number];
export type PublicApiError = PublicSchema<"Error">;
export type PublicApiErrorCode = PublicApiError["error"];

// Query parameters, as the API declares them.
export type PlayerQuery = QueryOf<"getLeaguePlayer">;
export type PlayerMatchesQuery = QueryOf<"getLeaguePlayerMatches">;
export type RostersQuery = QueryOf<"listLeagueRosters">;
export type RosterQuery = QueryOf<"getLeagueRoster">;
export type LeaderboardQuery = QueryOf<"getLeagueLeaderboard">;
export type StandingsQuery = QueryOf<"getLeagueStandings">;
export type FixturesQuery = QueryOf<"listLeagueFixtures">;
export type InventoryQuery = QueryOf<"getPlayerInventory">;
export type RatingCategory = NonNullable<PlayerQuery["category"]>;
export type LeaderboardMetric = NonNullable<LeaderboardQuery["metric"]>;
export type FixtureStatus = NonNullable<FixturesQuery["status"]>;

// Stat submission.
export type HeirMatchFile = StatSchema<"HeirMatchFile">;
export type HeirMatchMap = HeirMatchFile["maps"][number];
export type HeirMatchPlayer = NonNullable<HeirMatchMap["players"]>[number];
export type HeirMatchRound = NonNullable<HeirMatchMap["rounds"]>[number];
export type HeirMatchGamemode = HeirMatchFile["gamemode"];
export type MatchEntryReceipt = StatSchema<"MatchEntryReceipt">;
export type GamemodeCatalog = StatSchema<"GamemodeCatalog">;
export type StatSchemaCatalog = StatSchema<"StatSchemaCatalog">;
export type StatSchemaEntry = StatSchemaCatalog["schemas"][number];
export type BeginMatchRequest = StatSchema<"BeginMatchRequest">;
export type BeginMatchResponse = StatSchema<"BeginMatchResponse">;
export type AppendUnitsRequest = StatSchema<"AppendUnitsRequest">;
export type AppendUnitsResponse = StatSchema<"AppendUnitsResponse">;
export type HeartbeatMatchResponse = StatSchema<"HeartbeatMatchResponse">;
export type FinalizeMatchResponse = StatSchema<"FinalizeMatchResponse">;
export type UploadMatchRequest = StatSchema<"UploadMatchRequest">;
export type UploadMatchResponse = StatSchema<"UploadMatchResponse">;
export type GameSubmission = AppendUnitsRequest["games"][number];
export type RoundUnit = NonNullable<GameSubmission["rounds"]>[number];
export type GameResult = NonNullable<GameSubmission["result"]>;
export type StatApiError = StatSchema<"Error">;
export type StatApiErrorCode = StatApiError["error"];
export type StatOperationId = keyof StatOperations;
