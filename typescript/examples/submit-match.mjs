import {client, inputFile, live, submit} from "./support.mjs";

const supplied = inputFile();
if (live && submit && !supplied) throw new Error("Submitting real stats requires --file completed-match.json containing your actual match.");
const heir = client({keyRequired: true});
const catalog = await heir.stats.gamemodes();
console.log("Available gamemodes:", catalog.gamemodes.map(mode => ({key: mode.key, stats: mode.stats.map(stat => stat.key)})));
// The catalog template is directly assignable to HeirMatchFile in TypeScript. Copy it before filling it in.
const file = supplied ?? {...structuredClone(catalog.template), reference: "demo-match-2026-10-30"};
if (!file.reference) throw new Error("Persist a stable reference in the input file before submitting; reuse it with identical contents after a lost connection.");
if (live && !submit) {
  console.log("Preview only. Fill the template with your real data, save it, and use --file plus --submit to send it.");
  console.log(JSON.stringify(file, null, 2));
} else {
  const receipt = await heir.stats.submitMatch(file, {signal: AbortSignal.timeout(60_000)});
  console.log(receipt.status, receipt.replayed, receipt.problems);
}
