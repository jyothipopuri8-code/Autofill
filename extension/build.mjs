// Bundles the extension into dist/. `--e2e` adds http://localhost access and an auto-injected content
// script so browser tests can run without clicking permission prompts; never ship an e2e build.
import { build, context } from "esbuild";
import { copyFileSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";

const watch = process.argv.includes("--watch");
const e2e = process.argv.includes("--e2e");
const out = e2e ? "dist-e2e" : "dist";

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });

const common = { bundle: true, target: "chrome114", sourcemap: false, logLevel: "info", legalComments: "none" };
const jobs = [
  { ...common, entryPoints: { background: "src/background/index.ts" }, format: "esm", outdir: out },
  { ...common, entryPoints: { content: "src/content/index.ts" }, format: "iife", outdir: out },
  { ...common, entryPoints: { popup: "src/popup/popup.ts" }, format: "iife", outdir: out },
];

const manifest = JSON.parse(readFileSync("manifest.base.json", "utf8"));
if (e2e) {
  manifest.name += " (E2E build)";
  manifest.host_permissions.push("http://localhost/*", "http://127.0.0.1/*");
  manifest.content_scripts = [{ matches: ["http://localhost/*"], js: ["content.js"], run_at: "document_idle" }];
}
writeFileSync(`${out}/manifest.json`, JSON.stringify(manifest, null, 2));
for (const f of ["popup.html", "popup.css"]) copyFileSync(`src/popup/${f}`, `${out}/${f}`);

if (watch) {
  for (const j of jobs) await (await context(j)).watch();
} else {
  await Promise.all(jobs.map((j) => build(j)));
}
