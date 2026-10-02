# Browser extension

Manifest V3 Chrome/Edge extension (TypeScript, bundled with esbuild). See the top-level README for setup.

```bash
npm ci
npm run typecheck     # tsc --noEmit
npm test              # unit tests (the content-script API allow-list)
npm run build         # -> dist/ (load this folder unpacked)
npm run build:e2e     # -> dist-e2e/ (open shadow root; used only by the browser tests, never load it for real use)
```

Structure:

- `src/background/` service worker: the only code that talks to the agent. `allowlist.ts` is the list of endpoints the page-side script may request.
- `src/content/` page-side script: scanning (`scan.ts`), filling (`fill.ts`), panel UI (`panel.ts`), repeatable sections, ATS adapters (`adapters/`).
- `src/popup/` toolbar popup: pairing token, mode, per-site permission.
- `manifest.base.json` the manifest (fixed key, so the extension ID is the same for every install).
