// Content-script entry: ties scanning, the agent's answers, filling and the panel together.
// It reads nothing from the page until the user starts (or resumes) a session for this tab.
import type { AnalyzeResponse, ApiResponse, AttentionItem, Counts, FieldResult, JobInfo, Mode, ResumeState, TabState } from "../shared/types";
import { detectAdapter } from "./adapters";
import type { Adapter } from "./adapters/base";
import { sleep } from "./dom";
import { fillControl, FillEnv, FillOutcome, ResumeBlob } from "./fill";
import { collectJob } from "./job";
import { OwnershipTracker } from "./ownership";
import { Panel, PanelActions, PanelModel } from "./panel";
import { Control, Scanner, ScanResult } from "./scan";

const W = window as unknown as { __autofillAgent?: boolean };

async function api(method: string, path: string, body?: unknown, binary = false): Promise<ApiResponse> {
  try {
    return await chrome.runtime.sendMessage({ type: "api", method, path, body, binary });
  } catch {
    return { ok: false, status: 0, data: null, error: "The extension was reloaded. Refresh this page." };
  }
}

const EMBEDDED = /greenhouse\.io|lever\.co|myworkdayjobs|ashbyhq|icims\.com|smartrecruiters/i;
const MAX_FIELDS = 500;

function errorText(r: ApiResponse): string {
  if (r.error) return r.error;
  const d = r.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg).filter(Boolean).join("; ") || `Request failed (${r.status})`;
  return `Request failed (${r.status})`;
}

class Agent {
  private adapter: Adapter = detectAdapter(document, new URL(location.href));
  private tracker = new OwnershipTracker();
  private scanner = new Scanner(this.adapter, this.tracker);
  private panel: Panel;

  private sessionId: number | null = null;
  private applicationId: number | null = null;
  private pageIndex = 0;
  private job: JobInfo | null = null;
  private mode: Mode = "SAFE";

  private scan: ScanResult | null = null;
  private analysis: AnalyzeResponse | null = null;
  private results = new Map<string, FieldResult>();
  private attention: AttentionItem[] = [];
  private counts: Counts | undefined;
  private resume: ResumeState | undefined;
  private done = new Set<string>();      // keys filled by us on this page
  private attempted = new Set<string>(); // keys we tried (so a failure is not retried in a loop)
  private lastKeys = new Set<string>();
  private lastPath = location.pathname;
  private notices: string[] = [];
  private finalReview: PanelModel["final"] = null;
  private askSubmitted = false;
  private phase: PanelModel["phase"] = "idle";
  private message: string | undefined;
  private error: string | undefined;
  private duplicates: PanelModel["duplicates"];
  private busy = false;
  private pendingResumeLabel: string | undefined;
  private observer: MutationObserver | null = null;
  private debounce = 0;
  private forceCreate = false;

  constructor() {
    this.tracker.attach(document);
    this.panel = new Panel(this.actions());
    chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
      if (msg?.type === "ping") sendResponse({ ok: true, active: this.sessionId !== null });
      else if (msg?.type === "start") { void this.startFromPopup(); sendResponse({ ok: true }); }
      else if (msg?.type === "toggle") { this.panel.toggle(); sendResponse({ ok: true }); }
      return false;
    });
    document.addEventListener("click", (ev) => this.onUserClick(ev), true);
  }

  // --- startup -----------------------------------------------------------------------------

  async init(): Promise<void> {
    const st: TabState = await chrome.runtime.sendMessage({ type: "getTabState" }).catch(() => null);
    if (!st) return; // no session in this tab: stay completely idle
    const sess = await api("GET", `/api/v1/sessions/${st.sessionId}`);
    if (!sess.ok || ["COMPLETED", "ABANDONED"].includes(sess.data?.status)) {
      await chrome.runtime.sendMessage({ type: "setTabState", state: null }).catch(() => undefined);
      return;
    }
    this.adopt(sess.data);
    if (st.origin === location.origin) {
      this.pageIndex = st.pageIndex;
      await this.resumeHere();
    } else {
      this.phase = "resume";
      this.message = `Your application for ${sess.data.application?.company || "a job"} is in progress in this tab. Continue it on this page?`;
      this.render();
    }
  }

  private adopt(s: any): void {
    this.sessionId = s.id;
    this.applicationId = s.application_id ?? s.application?.id ?? null;
    this.pageIndex = s.current_page_index ?? 0;
  }

  private async startFromPopup(): Promise<void> {
    if (this.busy) return;
    if (this.sessionId !== null) { await this.resumeHere(); return; }
    this.panel.mount();
    await this.startSession(false);
  }

  private async saveTab(): Promise<void> {
    if (this.sessionId === null) return;
    await chrome.runtime.sendMessage({ type: "setTabState", state: { sessionId: this.sessionId, origin: location.origin, pageIndex: this.pageIndex } as TabState }).catch(() => undefined);
  }

  private async startSession(force: boolean): Promise<void> {
    this.busy = true;
    this.working("Connecting to your local agent…");
    try {
      const st = await api("GET", "/api/v1/status");
      if (!st.ok) { this.fail(errorText(st)); return; }
      this.job = collectJob(document, this.adapter, new URL(location.href));
      const settings = await api("GET", "/api/v1/settings");
      if (settings.ok && settings.data?.mode) this.mode = settings.data.mode;
      this.working("Creating an application session…");
      const res = await api("POST", "/api/v1/sessions", {
        company: this.job.company, job_title: this.job.job_title, job_id: this.job.job_id, url: this.job.url,
        location: this.job.location, job_description: this.job.job_description, ats: this.job.ats, force,
      });
      if (res.status === 409 && res.data?.detail?.code === "POSSIBLE_DUPLICATE") {
        this.phase = "duplicate";
        this.duplicates = res.data.detail.matches;
        this.render();
        return;
      }
      if (!res.ok) {
        const msg = errorText(res);
        this.fail(/resume/i.test(msg) ? `${msg}. Add a resume in the agent at http://127.0.0.1:8765/ui/ and try again.` : msg);
        return;
      }
      this.adopt(res.data);
      this.pageIndex = 0;
      await this.saveTab();
      await this.beginPage();
    } finally {
      this.busy = false;
    }
  }

  private async resumeHere(): Promise<void> {
    this.busy = true;
    try {
      this.job = collectJob(document, this.adapter, new URL(location.href));
      this.panel.mount();
      await this.saveTab();
      await this.beginPage();
    } finally {
      this.busy = false;
    }
  }

  /** Scan the current page, ask the agent, and (in Standard mode) fill what is ready. */
  private async beginPage(): Promise<void> {
    this.working("Reading this page…");
    await sleep(150); // let late-rendering forms settle
    this.observe();
    await this.analyze();
    if (this.mode === "STANDARD" && !this.analysis?.resume.blocked) await this.fill(undefined, false, true);
  }

  // --- analysis ----------------------------------------------------------------------------

  private async analyze(): Promise<boolean> {
    if (this.sessionId === null) return false;
    this.scan = this.scanner.scan(document);
    this.lastKeys = new Set(this.scan.controls.map((c) => c.key));
    const fields = this.scan.controls.map((c) => c.d).slice(0, MAX_FIELDS);
    const res = await api("POST", `/api/v1/sessions/${this.sessionId}/analyze`, { page_index: this.pageIndex, url: location.href, ats: this.adapter.id, fields });
    if (!res.ok) { this.fail(errorText(res)); return false; }
    const a = res.data as AnalyzeResponse;
    this.analysis = a;
    this.mode = a.mode;
    this.results = new Map(a.results.map((r) => [r.key, r]));
    this.attention = a.needs_attention;
    this.counts = a.counts;
    this.resume = a.resume;
    this.phase = "ready";
    this.error = undefined;
    this.render();
    return true;
  }

  private async validate(): Promise<void> {
    if (this.sessionId === null) return;
    this.scan = this.scanner.scan(document);
    const res = await api("POST", `/api/v1/sessions/${this.sessionId}/validate`, { page_index: this.pageIndex, ats: this.adapter.id, fields: this.scan.controls.map((c) => c.d).slice(0, MAX_FIELDS) });
    if (res.ok) {
      this.counts = res.data.counts;
      this.attention = res.data.needs_attention;
    } else this.error = errorText(res);
  }

  // --- filling -----------------------------------------------------------------------------

  private env(overwrite: boolean): FillEnv {
    return { tracker: this.tracker, overwriteSiteDefault: overwrite, resume: () => this.fetchResume() };
  }

  private async fetchResume(): Promise<ResumeBlob | null> {
    if (this.sessionId === null) return null;
    const r = await api("GET", `/api/v1/sessions/${this.sessionId}/resume-file`, undefined, true);
    if (!r.ok || !r.base64) { if (!r.ok) this.error = errorText(r); return null; }
    const bin = atob(r.base64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const exp = this.analysis?.resume.expected;
    const safe = (exp?.filename || r.headers?.["x-resume-filename"] || "resume.pdf").replace(/[\\/]+/g, "_");
    return { filename: safe, mime: r.headers?.["content-type"] || "application/octet-stream", bytes, sha256: r.headers?.["x-resume-sha256"] || "" };
  }

  /** Fill the given keys, or every ready non-sensitive field. Dependent fields that appear are handled in later rounds. */
  private async fill(keys: string[] | undefined, overwrite: boolean, auto = false): Promise<void> {
    if (this.sessionId === null || !this.scan) return;
    this.busy = true;
    this.tracker.attach(document);
    const outcomes: FillOutcome[] = [];
    const entries: NonNullable<FillOutcome["undo"]>[] = [];
    try {
      for (let round = 0; round < 3; round++) {
        const targets = this.targets(keys, auto);
        if (!targets.length) break;
        for (const [c, r] of targets) {
          this.attempted.add(c.key);
          const o = await fillControl(c, r, this.env(overwrite), this.analysis?.resume.expected?.sha256 ?? null);
          outcomes.push(o);
          if (o.outcome === "FILLED") { this.done.add(c.key); if (o.undo) entries.push(o.undo); }
          await sleep(35);
        }
        if (keys) break; // explicit single-field requests do not cascade
        await sleep(250);
        const before = this.lastKeys;
        const next = this.scanner.scan(document);
        const appeared = next.controls.some((c) => !before.has(c.key));
        if (!appeared) break;
        if (!(await this.analyze())) break; // dependent fields revealed: ask the agent about them too
      }
    } finally {
      this.busy = false;
    }
    this.tracker.pushBatch(entries);
    if (outcomes.length) {
      await api("POST", `/api/v1/sessions/${this.sessionId}/fill-report`, {
        page_index: this.pageIndex,
        fields: outcomes.map((o) => ({ key: o.key, outcome: o.outcome, ownership: "AGENT_FILLED", value: o.outcome === "FILLED" ? (o.value ?? null) : null, error: o.error ?? null })),
      });
      const failed = outcomes.filter((o) => o.outcome === "FAILED_TO_FILL").length;
      const ok = outcomes.filter((o) => o.outcome === "FILLED").length;
      this.notices = [`Filled ${ok} field${ok === 1 ? "" : "s"}${failed ? `; ${failed} could not be filled and need you` : ""}.`];
    }
    await this.validate();
    this.render();
  }

  private targets(keys: string[] | undefined, auto: boolean): Array<[Control, FieldResult]> {
    const out: Array<[Control, FieldResult]> = [];
    for (const c of this.scan?.controls ?? []) {
      const r = this.results.get(c.key);
      if (!r || this.done.has(c.key)) continue;
      if (keys) { if (keys.includes(c.key)) out.push([c, r]); continue; }
      if (this.attempted.has(c.key)) continue;
      const ready = (r.action === "fill" || r.action === "attach") && r.band === "READY" && !r.sensitive;
      if (ready && (!auto || r.auto || r.action === "attach")) out.push([c, r]);
    }
    return out;
  }

  // --- page changes ------------------------------------------------------------------------

  private observe(): void {
    if (this.observer) return;
    this.observer = new MutationObserver(() => {
      if (this.busy) return;
      window.clearTimeout(this.debounce);
      this.debounce = window.setTimeout(() => void this.onPageChanged(), 800);
    });
    this.observer.observe(document.body, { childList: true, subtree: true });
    window.setInterval(() => { if (location.pathname !== this.lastPath && !this.busy) void this.onPageChanged(); }, 1000);
  }

  private async onPageChanged(): Promise<void> {
    if (this.busy || this.sessionId === null || this.phase === "idle") return;
    const next = this.scanner.scan(document);
    const keys = new Set(next.controls.map((c) => c.key));
    const same = [...keys].filter((k) => this.lastKeys.has(k)).length;
    const overlap = same / Math.max(1, Math.max(keys.size, this.lastKeys.size));
    const pathChanged = location.pathname !== this.lastPath;
    if (!pathChanged && keys.size === this.lastKeys.size && overlap === 1) return; // nothing new
    const newPage = (pathChanged && overlap < 0.9) || overlap < 0.4;
    this.lastPath = location.pathname;
    if (newPage && keys.size) {
      this.pageIndex++;
      this.done.clear(); this.attempted.clear(); this.finalReview = null; this.notices = [];
      await api("PATCH", `/api/v1/sessions/${this.sessionId}`, { current_page_index: this.pageIndex, current_page_url: location.href });
      await this.saveTab();
    }
    this.busy = true;
    try {
      await this.analyze();
      if (this.mode === "STANDARD" && !this.analysis?.resume.blocked) { this.busy = false; await this.fill(undefined, false, true); }
    } finally { this.busy = false; }
  }

  /** The user's own clicks on submit buttons are only observed, never made for them. */
  private onUserClick(ev: MouseEvent): void {
    if (!ev.isTrusted || this.sessionId === null) return;
    const t = ev.target as HTMLElement | null;
    const btn = t?.closest<HTMLElement>("button,input[type=submit],input[type=button],a[role=button],[role=button]");
    if (!btn) return;
    if (this.adapter.navButtons(document).submit.includes(btn)) {
      window.setTimeout(() => { this.askSubmitted = true; this.render(); }, 1500);
    }
  }

  // --- panel -------------------------------------------------------------------------------

  private working(message: string): void { this.phase = "working"; this.message = message; this.render(); }
  private fail(message: string): void { this.phase = "error"; this.error = message; this.render(); }

  private addEntries(): PanelModel["addEntries"] {
    if (!this.analysis || !this.scan) return [];
    const have: Record<string, number> = {};
    for (const c of this.scan.controls) if (c.d.section) have[c.d.section.name] = Math.max(have[c.d.section.name] ?? 0, c.d.section.index + 1);
    const out: PanelModel["addEntries"] = [];
    for (const name of ["experience", "education", "certification", "language"] as const) {
      const want = Math.min(this.analysis.section_counts[name] ?? 0, 8);
      // Only offer this where the page already shows that section; otherwise there is nothing to add to.
      if (name in have && want > have[name]) out.push({ name, have: have[name], want });
    }
    return out;
  }

  private render(): void {
    const controls = new Map((this.scan?.controls ?? []).map((c) => [c.key, c]));
    const ready = [...this.results.values()].filter((r) => (r.action === "fill" || r.action === "attach") && !this.done.has(r.key) && controls.has(r.key));
    const embedded = (this.scan?.controls.length ?? 0) < 3
      ? document.querySelector<HTMLIFrameElement>("iframe[src]")?.src.match(EMBEDDED)?.[0] ?? null : null;
    this.panel.render({
      phase: this.phase, message: this.message, error: this.error, job: this.job ?? undefined, mode: this.mode,
      counts: this.counts, resume: this.resume, ready, attention: this.attention, controls, results: this.results,
      duplicates: this.duplicates, notices: this.notices, canUndo: this.tracker.lastBatchSize > 0, addEntries: this.addEntries(),
      final: this.finalReview, askSubmitted: this.askSubmitted, embeddedAts: embedded, noFields: this.phase === "ready" && (this.counts?.detected ?? 0) === 0,
    });
    this.pendingResumeLabel = undefined;
  }

  private actions(): PanelActions {
    const refill = async (key: string) => {
      const r = this.results.get(key);
      if (r && (r.action === "fill" || r.action === "attach") && this.scan?.byKey.has(key)) await this.fill([key], false);
    };
    return {
      start: () => void this.startSession(false),
      startAnyway: () => void this.startSession(true),
      cancel: () => { this.phase = "idle"; this.render(); },
      continueHere: () => void this.resumeHere(),
      continueSession: async (id) => {
        const s = await api("GET", `/api/v1/sessions/${id}`);
        if (!s.ok) { this.fail(errorText(s)); return; }
        this.adopt(s.data);
        await this.saveTab();
        await this.resumeHere();
      },
      fillReady: () => { this.notices = []; void this.fill(undefined, false); },
      fillKey: (key, overwrite) => { this.notices = []; void this.fill([key], overwrite); },
      rescan: async () => { this.notices = []; this.done.clear(); this.attempted.clear(); this.working("Rescanning…"); await this.analyze(); },
      undo: async () => {
        const res = await this.tracker.undoLast();
        this.done.clear(); this.attempted.clear();
        this.notices = [res.restored || res.skipped
          ? `Undid ${res.restored} field${res.restored === 1 ? "" : "s"}${res.skipped ? `. ${res.skipped} could not be undone (you changed them, or they are custom dropdowns).` : "."}`
          : "Nothing to undo."];
        await this.analyze();
      },
      show: (key) => { const c = this.scan?.byKey.get(key); if (c) this.panel.highlight(c.el); },
      saveAnswer: async (key, value, remember) => {
        const res = await api("POST", `/api/v1/sessions/${this.sessionId}/answers`, { page_index: this.pageIndex, field_key: key, value, remember });
        if (!res.ok) { this.error = errorText(res); this.render(); return; }
        this.notices = res.data?.note ? [res.data.note] : [];
        this.error = undefined;
        this.attempted.delete(key);
        if (await this.analyze()) await refill(key);
      },
      resolveConflict: async (field, choice, value) => {
        const res = await api("POST", `/api/v1/sessions/${this.sessionId}/conflicts/resolve`, { canonical_field: field, choice, value: choice === "custom" ? value : undefined });
        if (!res.ok) { this.error = errorText(res); this.render(); return; }
        this.attempted.clear();
        if (await this.analyze()) {
          const keys = [...this.results.values()].filter((r) => r.canonical_field === field && r.action === "fill").map((r) => r.key);
          if (keys.length) await this.fill(keys, false);
        }
      },
      chooseResume: async (id) => {
        const res = await api("POST", `/api/v1/sessions/${this.sessionId}/resume`, { resume_id: id });
        if (!res.ok) { this.error = errorText(res); this.render(); return; }
        this.attempted.clear();
        await this.analyze();
      },
      addEntries: async (name) => {
        const list = this.addEntries().find((e) => e.name === name);
        if (!list) return;
        this.busy = true;
        this.working(`Adding ${name} entries…`);
        let added = 0;
        for (let i = list.have; i < list.want; i++) {
          if (!(await this.adapter.addAnother(document, name as any))) break;
          added++;
        }
        this.busy = false;
        this.notices = [added ? `Added ${added} ${name} entr${added === 1 ? "y" : "ies"}.` : `Could not find the "add" button for ${name}. Add the entry yourself, then press Rescan.`];
        this.attempted.clear();
        await this.analyze();
      },
      finalReview: async () => {
        await this.validate();
        const res = await api("GET", `/api/v1/sessions/${this.sessionId}/final-review`);
        this.finalReview = res.ok ? res.data : null;
        if (!res.ok) this.error = errorText(res);
        this.render();
      },
      markSubmitted: async () => {
        if (this.applicationId !== null) await api("PATCH", `/api/v1/applications/${this.applicationId}`, { status: "SUBMITTED" });
        await api("PATCH", `/api/v1/sessions/${this.sessionId}`, { status: "COMPLETED" });
        await chrome.runtime.sendMessage({ type: "setTabState", state: null }).catch(() => undefined);
        this.askSubmitted = false;
        this.sessionId = null;
        this.notices = ["Marked as submitted. Good luck!"];
        this.phase = "idle";
        this.render();
      },
      dismissSubmitted: () => { this.askSubmitted = false; this.render(); },
      openEmbedded: () => {
        const src = document.querySelector<HTMLIFrameElement>("iframe[src]")?.src;
        if (src && /^https:/.test(src)) window.open(src, "_blank", "noopener");
      },
      close: () => this.panel.hide(),
    };
  }
}

if (!W.__autofillAgent) {
  W.__autofillAgent = true;
  const agent = new Agent();
  const go = () => void agent.init();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", go, { once: true });
  else go();
}
