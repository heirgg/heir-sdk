import {client, leagueRef, identity} from "./support.mjs";

const league = client().league(leagueRef);
// A signal bounds the entire operation, including retries. timeoutMs bounds each individual attempt.
const options = {signal: AbortSignal.timeout(10_000)};
const {player} = await league.player("mordhau", process.env.HEIR_PLAYER_ID ?? identity, {}, options);
console.log(player ? `${player.displayName}: ${player.mmr?.value ?? "unrated"}` : "No current League member is linked to that identity.");
for await (const roster of await league.rosters({}, options)) console.log(roster.name, roster.teamMmr);
