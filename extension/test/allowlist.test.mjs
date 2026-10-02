// Run with `npm test`. Bundles the TypeScript module on the fly so the test uses the real code.
import assert from "node:assert/strict";
import { test } from "node:test";
import { build } from "esbuild";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const dir = mkdtempSync(join(tmpdir(), "afa-"));
const out = join(dir, "allowlist.mjs");
await build({ entryPoints: ["src/background/allowlist.ts"], bundle: true, format: "esm", outfile: out, logLevel: "silent" });
const { allowed } = await import(pathToFileURL(out).href);

test("what the panel needs is allowed", () => {
  for (const [m, p] of [
    ["GET", "/api/v1/status"], ["GET", "/api/v1/settings"], ["POST", "/api/v1/sessions"], ["GET", "/api/v1/sessions?status=ACTIVE&url=https://a.example/x"],
    ["GET", "/api/v1/sessions/12"], ["PATCH", "/api/v1/sessions/12"], ["POST", "/api/v1/sessions/12/analyze"], ["POST", "/api/v1/sessions/3/answers"],
    ["POST", "/api/v1/sessions/3/conflicts/resolve"], ["POST", "/api/v1/sessions/3/resume"], ["POST", "/api/v1/sessions/3/fill-report"],
    ["POST", "/api/v1/sessions/3/validate"], ["GET", "/api/v1/sessions/3/attention"], ["GET", "/api/v1/sessions/3/final-review"],
    ["GET", "/api/v1/sessions/3/resume-file"], ["PATCH", "/api/v1/applications/4"],
  ]) assert.ok(allowed(m, p), `${m} ${p}`);
});

test("the page-side script can never reach personal data or destructive endpoints", () => {
  for (const [m, p] of [
    ["GET", "/api/v1/profile"], ["PATCH", "/api/v1/profile"], ["DELETE", "/api/v1/profile"], ["GET", "/api/v1/profile/sensitive"],
    ["PUT", "/api/v1/profile/sensitive/gender"], ["GET", "/api/v1/answers"], ["PUT", "/api/v1/answers/desired_salary"], ["GET", "/api/v1/memory"],
    ["GET", "/api/v1/resumes"], ["GET", "/api/v1/resumes/1/data"], ["POST", "/api/v1/resumes"], ["DELETE", "/api/v1/resumes/1"],
    ["GET", "/api/v1/data/export"], ["POST", "/api/v1/data/delete"], ["PUT", "/api/v1/settings"], ["GET", "/api/v1/applications"],
    ["DELETE", "/api/v1/applications/1"], ["DELETE", "/api/v1/sessions/1"], ["GET", "/api/v1/applications/1"], ["GET", "/api/v1/health"],
  ]) assert.ok(!allowed(m, p), `${m} ${p} must be refused`);
});

test("wrong methods, traversal and look-alike paths are refused", () => {
  for (const [m, p] of [
    ["DELETE", "/api/v1/sessions/1"], ["PUT", "/api/v1/sessions/1"], ["GET", "/api/v1/sessions/1/analyze"], ["POST", "/api/v1/sessions/1/attention"],
    ["GET", "/api/v1/sessions/1/../profile"], ["GET", "/api/v1/sessions/1/%2e%2e/profile"], ["GET", "/api/v1/sessions/abc"], ["GET", "/api/v1/sessions/1x"],
    ["POST", "/api/v1/sessions/1/analyze/extra"], ["POST", "/api/v1/sessions/1/analyze?x=1"], ["POST", "/api/v1/sessions/1/analyze\n"],
    ["GET", "http://evil.example/api/v1/status"], ["GET", "//evil.example/api/v1/status"], ["GET", "/api/v1/status/"], ["GET", " /api/v1/status"],
    ["GET", "/api/v1/sessions?x=<script>"], ["GET", "/api/v1/sessions?x=a b"], ["get", "/api/v1/status"], ["OPTIONS", "/api/v1/status"],
  ]) assert.ok(!allowed(m, p), `${m} ${JSON.stringify(p)} must be refused`);
});
