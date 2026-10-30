import {client, fixture, inputFile, live, submit} from "./support.mjs";

const supplied = inputFile();
if (live && !supplied) throw new Error("Supply --file tracking.json with matchId, startedAt, and games containing your actual units/results.");
const journal = supplied ?? fixture("uploadMatch").requestBody;
const heir = client({keyRequired: true});
const schemas = await heir.stats.schemas();
console.log("Tracking schemas:", schemas.schemas.map(schema => ({schemaRef: schema.schemaRef, counters: schema.counters})));
const begin = {matchId: journal.matchId, startedAt: journal.startedAt};
const request = {games: journal.games};
if (live && !submit) {
  // An upload validates the whole document without opening a live session. Every real tracking call supports dryRun too.
  console.log(await heir.stats.upload(journal, {dryRun: true, idempotencyKey: `${journal.matchId}:validate`}));
} else {
  // Persist this journal before beginning. A restarted producer can repeat exactly these requests and keys.
  // If producing multiple batches, persist a distinct batch ID and payload for every append.
  const options = step => ({idempotencyKey: `${journal.matchId}:${step}`, signal: AbortSignal.timeout(60_000)});
  await heir.stats.beginMatch(begin, options("begin"));
  await heir.stats.appendUnits(journal.matchId, request, options("batch-0"));
  await heir.stats.heartbeat(journal.matchId, options("heartbeat-0"));
  console.log(await heir.stats.finalize(journal.matchId, options("finalize")));
}
