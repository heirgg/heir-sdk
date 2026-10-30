import {execFileSync} from "node:child_process";
import {mkdtempSync, rmSync, writeFileSync} from "node:fs";
import {tmpdir} from "node:os";
import {join} from "node:path";
import {fileURLToPath} from "node:url";
import assert from "node:assert/strict";

const root = fileURLToPath(new URL("../", import.meta.url));
const temporary = mkdtempSync(join(tmpdir(), "heir-consumer-"));
const npm = process.env.npm_execpath;
if (!npm) throw new Error("Run this check with npm run test:package.");
const run = (command, args, cwd = temporary) => execFileSync(command, args, {cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"]});
const runNpm = (args, cwd) => run(process.execPath, [npm, ...args], cwd);
try {
  const packed = JSON.parse(runNpm(["pack", "--json", "--ignore-scripts", "--pack-destination", temporary, "--cache", join(temporary, "cache")], root))[0];
  assert(packed.files.some(file => file.path === "LICENSE"));
  assert(packed.files.some(file => file.path === "dist/index.d.cts"));
  writeFileSync(join(temporary, "package.json"), JSON.stringify({private: true}));
  // The tarball has no runtime dependencies. Installation is offline and runs no lifecycle scripts.
  runNpm(["install", "--offline", "--ignore-scripts", "--no-audit", "--no-fund", "--cache", join(temporary, "cache"), join(temporary, packed.filename)]);
  const source = 'import {Heir, HeirInputError, type HeirMatchFile} from "@heirgg/sdk";\nconst client = new Heir();\nconst file: HeirMatchFile = {format:"heir-match-v1", startedAt:"2026-10-30T12:00:00Z", maps:[]};\nvoid [client, file, HeirInputError];\n';
  writeFileSync(join(temporary, "consumer.cts"), source);
  writeFileSync(join(temporary, "consumer.mts"), source);
  const compiler = join(root, "node_modules", "typescript", "bin", "tsc");
  for (const mode of ["Node16", "NodeNext"]) {
    run(process.execPath, [compiler, "--noEmit", "--strict", "--skipLibCheck", "--target", "ES2022", "--module", mode, "--moduleResolution", mode, "consumer.cts", "consumer.mts"]);
    console.log(`Packed ESM/CommonJS consumer declarations passed (${mode}).`);
  }
  for (const [file, load] of [["runtime.cjs", 'const {Heir} = require("@heirgg/sdk");'], ["runtime.mjs", 'import {Heir} from "@heirgg/sdk";']]) {
    writeFileSync(join(temporary, file), `${load}\nif (new Heir().authenticated) throw new Error("Unexpected authentication");\n`);
    run(process.execPath, [file]);
  }
  // A pending SDK operation must keep a one-off Node integration alive through retry backoff.
  writeFileSync(join(temporary, "retry.cjs"), `
const {Heir} = require("@heirgg/sdk");
let attempts = 0;
const client = new Heir({fetch: async () => {if (++attempts === 1) throw new Error("reset"); return new Response("{}");}});
client.league("nacl").config().then(() => {if (attempts !== 2) throw new Error("Wrong attempts"); console.log("completed");}, error => {console.error(error); process.exitCode = 1;});
`);
  assert.equal(run(process.execPath, ["retry.cjs"]).trim(), "completed");
  console.log("Packed ESM/CommonJS runtime and real-timer subprocess retry passed.");
} catch (error) {
  if (error.stdout) process.stdout.write(error.stdout);
  if (error.stderr) process.stderr.write(error.stderr);
  throw error;
} finally {
  rmSync(temporary, {recursive: true, force: true});
}
