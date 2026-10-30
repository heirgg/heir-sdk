import {readFileSync} from "node:fs";
import {Heir} from "@heirgg/sdk";

export const live = process.argv.includes("--live");
export const submit = process.argv.includes("--submit");
export const leagueRef = live ? process.env.HEIR_LEAGUE ?? "nacl" : "nacl";
export const identity = "A1B2C3D4E5F67890";
export const id = "9f6d2a70-0000-4000-8000-000000000000";
export const fixtures = JSON.parse(readFileSync(new URL("../../tests/contracts.json", import.meta.url), "utf8")).cases;
export const fixture = operationId => fixtures.find(test => test.operationId === operationId);

export function inputFile() {
  const index = process.argv.indexOf("--file");
  if (index < 0) return undefined;
  if (!process.argv[index + 1]) throw new Error("--file needs a JSON filename.");
  return JSON.parse(readFileSync(process.argv[index + 1], "utf8"));
}

export function client({keyRequired = false} = {}) {
  if (live) {
    if (!process.env.HEIR_BASE_URL) throw new Error("Set HEIR_BASE_URL explicitly before using --live.");
    if (keyRequired && !process.env.HEIR_API_KEY) throw new Error("Set HEIR_API_KEY on the server before this example contacts the API.");
    return new Heir({baseUrl: process.env.HEIR_BASE_URL, apiKey: process.env.HEIR_API_KEY});
  }
  console.log("Offline fixture mode; no requests leave this process.");
  return new Heir({apiKey: "example-key", fetch: async (url, init) => {
    const path = new URL(url).pathname;
    const found = fixtures.find(test => test.path === path && test.method === init.method);
    if (!found) throw new Error(`No offline fixture for ${init.method} ${path}`);
    return new Response(JSON.stringify(found.responseBody), {headers: {"content-type": "application/json"}});
  }});
}
