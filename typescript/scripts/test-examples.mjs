import {execFileSync} from "node:child_process";
import {fileURLToPath} from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const env = {...process.env};
for (const key of Object.keys(env)) if (key.startsWith("HEIR_")) delete env[key];
for (const name of ["public-read", "eligibility", "submit-match", "tracking"]) {
  const output = execFileSync(process.execPath, [`examples/${name}.mjs`], {cwd: root, env, encoding: "utf8"});
  if (!output.includes("Offline fixture mode")) throw new Error(`${name} did not run offline.`);
  console.log(`${name} example passed offline.`);
}
