import { build } from "esbuild";
import { Miniflare } from "miniflare";
import { spawn } from "node:child_process";
import { access, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const checkout = process.env.SAILRY_LEGACY_CHECKOUT;
if (!checkout) throw new Error("Set SAILRY_LEGACY_CHECKOUT to the historical Rust workspace described in README.md");
const workspace = resolve(checkout);
await access(join(workspace, "Cargo.toml"));

const project = fileURLToPath(new URL("..", import.meta.url));
const desktop = process.argv.includes("--desktop");
const host = process.argv.includes("--host");
const edgeone = process.argv.includes("--edgeone");
const target = host ? ["-p", "sailry-host", "--test", "lifecycle"]
  : desktop ? ["-p", "sailry-desktop"]
  : ["-p", "sailry-node-runtime", "--test", "short_codes"];
const tests = host ? ["short_code_pairs_a_headless_process", "sharing_controls_the_existing_headless_node"]
  : desktop ? ["sharing_lifecycle"]
  : ["exchanges_code_and_authenticates_peer", "stops_sharing_after_pairing"];

let directory;
try {
  let start;
  if (edgeone) {
    directory = await mkdtemp(join(tmpdir(), "sailry-edgeone-fixture-"));
    const outfile = join(directory, "fixture.mjs");
    await build({ absWorkingDir: project, entryPoints: ["test/edgeone-server.ts"], bundle: true,
      outfile, format: "esm", platform: "node" });
    start = (await import(pathToFileURL(outfile).href)).start;
  } else {
    const output = await build({ absWorkingDir: project, entryPoints: ["src/worker.ts"], bundle: true,
      write: false, format: "esm", platform: "browser" });
    start = () => new Miniflare({ modules: true, script: output.outputFiles[0].text,
      host: "127.0.0.1", port: 0, compatibilityDate: "2025-01-01",
      durableObjects: { CODES: { className: "PairingCodes", useSQLite: true } } });
  }

  for (const test of tests) {
    const service = await start();
    try {
      const address = await service.ready;
      const child = spawn("cargo", ["test", "--locked", ...target, test, "--", "--ignored"], {
        cwd: workspace, stdio: "inherit", env: { ...process.env, SAILRY_TEST_RELAY: address.toString() },
      });
      process.exitCode = await new Promise((resolve, reject) => {
        child.once("error", reject);
        child.once("exit", code => resolve(code ?? 1));
      });
    } finally { await service.dispose(); }
    if (process.exitCode) break;
  }
} finally { if (directory) await rm(directory, { recursive: true }); }
