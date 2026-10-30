import {client, fixture, inputFile, leagueRef, live} from "./support.mjs";

const input = inputFile();
if (live && !input) throw new Error("Supply --file eligibility.json with credential, identifiers, fixtureId, rosterId, and gamemode.");
const request = input ?? fixture("checkLeagueEligibility").requestBody;
const verdict = await client({keyRequired: true}).league(leagueRef).checkEligibility(request, {signal: AbortSignal.timeout(10_000)});
for (const player of verdict.players) console.log(player.identifier, player.eligible, player.reasons);
// This is advisory: a successful eligibility read does not reserve seats.
