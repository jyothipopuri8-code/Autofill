// The in-page control panel (doc §13, §24, §32). It lives in a closed shadow root so the page cannot read or
// restyle it, and everything the page controls (labels, values) is inserted as text, never as HTML.
import type { AnalyzeResponse, AttentionItem, Counts, FieldResult, JobInfo, Mode, ResumeState } from "../shared/types";
import { HOST_ATTR, displayLabel } from "./scan";
import type { Control } from "./scan";

export interface DuplicateMatch { id: number; company: string | null; job_title: string | null; status: string; reason: string; active_session_id: number | null }

export interface PanelModel {
  phase: "idle" | "working" | "error" | "duplicate" | "resume" | "ready";
  message?: string;
  error?: string;
  job?: JobInfo;
  mode: Mode;
  pageIndex: number;
  counts?: Counts;
  resume?: ResumeState;
  ready: FieldResult[];
  attention: AttentionItem[];
  controls: Map<string, Control>;
  results: Map<string, FieldResult>;
  duplicates?: DuplicateMatch[];
  notices: string[];
  canUndo: boolean;
  addEntries: Array<{ name: string; have: number; want: number }>;
  final?: { ready: boolean; headline: string; checks: Array<{ id: string; label: string; ok: boolean; detail: string | null }>; note: string } | null;
  askSubmitted: boolean;
  embeddedAts?: string | null;
  noFields: boolean;
}

export interface PanelActions {
  start(): void;
  continueSession(id: number): void;
  startAnyway(): void;
  cancel(): void;
  continueHere(): void;
  fillReady(): void;
  fillKey(key: string, overwrite: boolean): void;
  rescan(): void;
  undo(): void;
  show(key: string): void;
  saveAnswer(key: string, value: string, remember: boolean): void;
  resolveConflict(field: string, choice: "profile" | "resume" | "custom", value?: string): void;
  chooseResume(id: number): void;
  addEntries(name: string): void;
  finalReview(): void;
  markSubmitted(): void;
  dismissSubmitted(): void;
  openEmbedded(): void;
  close(): void;
}

const CSS = `
:host{all:initial}
*{box-sizing:border-box}
.wrap{position:fixed;right:16px;bottom:16px;width:392px;max-width:calc(100vw - 32px);max-height:min(82vh,720px);display:flex;flex-direction:column;
 font:13px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--fg);background:var(--bg);border:1px solid var(--bd);border-radius:12px;
 box-shadow:0 10px 40px rgba(0,0,0,.28);z-index:2147483647;--fg:#1c2330;--mut:#5b6678;--bg:#fff;--bd:#d9dee7;--card:#f5f7fa;--ac:#2557d6;--acfg:#fff;--ok:#12794a;--warn:#9a5b00;--bad:#b3261e}
@media (prefers-color-scheme:dark){.wrap{--fg:#e6eaf2;--mut:#9aa6ba;--bg:#171c26;--bd:#2b3445;--card:#202838;--ac:#6b93ff;--acfg:#0c1220;--ok:#4cc38a;--warn:#e6a23c;--bad:#ff7a70}}
.wrap.min{width:auto;max-height:none}
header{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid var(--bd)}
header .t{flex:1;min-width:0}
header b{display:block;font-size:13px}
header span{display:block;color:var(--mut);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mode{font-size:11px;padding:2px 7px;border-radius:99px;background:var(--card);border:1px solid var(--bd);color:var(--mut)}
button{font:inherit;cursor:pointer;border-radius:8px;border:1px solid var(--bd);background:var(--card);color:var(--fg);padding:6px 10px}
button:hover{border-color:var(--ac)}
button.pri{background:var(--ac);color:var(--acfg);border-color:var(--ac);font-weight:600}
button.ghost{border-color:transparent;background:transparent;padding:4px 8px}
button:disabled{opacity:.5;cursor:default}
.body{overflow:auto;padding:10px 12px;display:flex;flex-direction:column;gap:10px}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{padding:3px 8px;border-radius:99px;background:var(--card);border:1px solid var(--bd);font-size:12px}
.chip.ok{color:var(--ok)}.chip.warn{color:var(--warn)}.chip.bad{color:var(--bad)}
.row{display:flex;gap:6px;flex-wrap:wrap}
.banner{padding:8px 10px;border-radius:8px;border:1px solid var(--bd);background:var(--card)}
.banner.bad{border-color:var(--bad)}.banner.warn{border-color:var(--warn)}
.card{padding:8px 10px;border-radius:8px;border:1px solid var(--bd);background:var(--card);display:flex;flex-direction:column;gap:6px}
.card h4{margin:0;font-size:13px}
h4.sec{margin:4px 0 0;font-size:13px}
ul.plain{list-style:none;padding:0}
.card button{align-self:flex-start}
.card .why{color:var(--mut);font-size:12px}
.card .val{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;word-break:break-word}
.tag{font-size:11px;color:var(--mut)}
.req{color:var(--bad)}
input[type=text],textarea,select{font:inherit;width:100%;padding:6px 8px;border-radius:6px;border:1px solid var(--bd);background:var(--bg);color:var(--fg)}
textarea{min-height:64px;resize:vertical}
label.chk{display:flex;gap:6px;align-items:center;font-size:12px;color:var(--mut)}
details summary{cursor:pointer;color:var(--mut)}
ul{margin:4px 0 0;padding-left:18px}
.ck{display:flex;gap:6px}.ck.ok{color:var(--ok)}.ck.bad{color:var(--bad)}
.foot{color:var(--mut);font-size:11px;padding:8px 12px;border-top:1px solid var(--bd)}
.hl{position:fixed;pointer-events:none;border:3px solid var(--ac,#2557d6);border-radius:6px;box-shadow:0 0 0 4px rgba(37,87,214,.25);z-index:2147483646;transition:opacity .3s}
`;

function h<K extends keyof HTMLElementTagNameMap>(tag: K, props: Record<string, any> = {}, ...kids: Array<Node | string | null | false | undefined>): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v as EventListener);
    else if (k in el && k !== "list") (el as any)[k] = v;
    else el.setAttribute(k, String(v));
  }
  for (const kid of kids) if (kid !== null && kid !== undefined && kid !== false) el.append(kid);
  return el;
}

export class Panel {
  private host: HTMLElement;
  private root: ShadowRoot;
  private wrap!: HTMLElement;
  private minimized = false;
  private model: PanelModel | null = null;
  private hl: HTMLElement | null = null;
  private drafts = new Map<string, string>(); // typed-but-unsaved answers survive re-renders

  constructor(private act: PanelActions) {
    this.host = document.createElement("div");
    this.host.setAttribute(HOST_ATTR, "");
    this.host.style.cssText = "all:initial;position:fixed;z-index:2147483647;";
    this.root = this.host.attachShadow({ mode: __E2E__ ? "open" : "closed" });
    try {
      const sheet = new CSSStyleSheet();
      sheet.replaceSync(CSS);
      this.root.adoptedStyleSheets = [sheet];
    } catch {
      this.root.append(h("style", { textContent: CSS }));
    }
  }

  mount(): void {
    if (!this.host.isConnected) (document.body || document.documentElement).append(this.host);
  }

  hide(): void { this.host.remove(); }
  get visible(): boolean { return this.host.isConnected; }

  toggle(): void {
    if (this.visible) this.hide(); else { this.mount(); if (this.model) this.render(this.model); }
  }

  highlight(el: HTMLElement): void {
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    this.hl?.remove();
    const box = h("div", { class: "hl" });
    this.root.append(box);
    this.hl = box;
    const place = () => {
      const r = el.getBoundingClientRect();
      Object.assign(box.style, { left: `${r.left - 4}px`, top: `${r.top - 4}px`, width: `${r.width + 8}px`, height: `${r.height + 8}px` });
    };
    place();
    const t = window.setInterval(place, 60);
    window.setTimeout(() => { window.clearInterval(t); box.style.opacity = "0"; window.setTimeout(() => box.remove(), 320); }, 2600);
  }

  render(m: PanelModel): void {
    this.model = m;
    this.mount();
    this.root.querySelector(".wrap")?.remove();
    const wrap = h("div", { class: `wrap${this.minimized ? " min" : ""}`, "data-page": m.pageIndex, "data-phase": m.phase });
    this.wrap = wrap;

    const title = h("div", { class: "t" }, h("b", {}, "Autofill Agent"),
      m.job ? h("span", {}, [m.job.company, m.job.job_title].filter(Boolean).join(" · ") || "This page") : null);
    wrap.append(h("header", {}, title, h("span", { class: "mode", title: "Change the mode from the toolbar popup" }, m.mode === "MANUAL_ASSIST" ? "Manual assist" : m.mode === "STANDARD" ? "Standard" : "Safe"),
      h("button", { class: "ghost", title: this.minimized ? "Expand" : "Minimize", onclick: () => { this.minimized = !this.minimized; this.render(m); } }, this.minimized ? "▢" : "–"),
      h("button", { class: "ghost", title: "Close the panel (your session stays saved)", onclick: () => this.act.close() }, "×")));
    if (this.minimized) { this.root.append(wrap); return; }

    const body = h("div", { class: "body" });
    wrap.append(body);
    this.renderBody(body, m);
    wrap.append(h("div", { class: "foot" }, "This panel never submits your application. You review and submit it yourself."));
    this.root.append(wrap);
  }

  private renderBody(body: HTMLElement, m: PanelModel): void {
    if (m.phase === "idle") {
      for (const n of m.notices) body.append(h("div", { class: "banner" }, n));
      body.append(h("div", {}, "Start an application session to scan this page and prepare answers from your profile and resume."),
        h("div", { class: "row" }, h("button", { class: "pri", onclick: () => this.act.start() }, "Start on this page")));
      if (m.embeddedAts) body.append(this.embeddedBanner(m));
      return;
    }
    if (m.phase === "working") { body.append(h("div", { class: "banner" }, m.message || "Working…")); return; }
    if (m.phase === "error") {
      body.append(h("div", { class: "banner bad" }, m.error || "Something went wrong."),
        h("div", { class: "row" }, h("button", { onclick: () => this.act.start() }, "Try again")));
      return;
    }
    if (m.phase === "resume") {
      body.append(h("div", {}, m.message || "An application session is in progress in this tab."),
        h("div", { class: "row" }, h("button", { class: "pri", onclick: () => this.act.continueHere() }, "Continue on this page"), h("button", { class: "ghost", onclick: () => this.act.cancel() }, "Not now")));
      return;
    }
    if (m.phase === "duplicate") {
      body.append(h("div", { class: "banner warn" }, h("b", {}, "Possible duplicate application"),
        h("ul", {}, ...(m.duplicates || []).map((d) => h("li", {}, `${d.company || "Unknown company"} · ${d.job_title || "Unknown role"} (${d.status.toLowerCase().replace(/_/g, " ")}): ${d.reason}`)))));
      const row = h("div", { class: "row" });
      for (const d of (m.duplicates || []).filter((x) => x.active_session_id)) {
        row.append(h("button", { class: "pri", onclick: () => this.act.continueSession(d.active_session_id!) }, `Continue earlier session (${d.company || d.job_title || d.id})`));
      }
      row.append(h("button", { onclick: () => this.act.startAnyway() }, "Start a new one anyway"), h("button", { class: "ghost", onclick: () => this.act.cancel() }, "Cancel"));
      body.append(row);
      return;
    }

    // --- ready ------------------------------------------------------------------------
    if (m.error) body.append(h("div", { class: "banner bad" }, m.error));
    for (const n of m.notices) body.append(h("div", { class: "banner" }, n));
    if (m.embeddedAts) body.append(this.embeddedBanner(m));
    if (m.resume?.blocked) body.append(this.resumeBanner(m.resume));
    else if (m.resume?.warning) body.append(h("div", { class: "banner warn" }, m.resume.warning, " Review it in the agent before relying on resume-based answers."));
    if (m.askSubmitted) {
      body.append(h("div", { class: "banner warn" }, h("div", {}, "You clicked a submit button. Did the application go through?"),
        h("div", { class: "row" }, h("button", { class: "pri", onclick: () => this.act.markSubmitted() }, "Yes, mark it submitted"), h("button", { onclick: () => this.act.dismissSubmitted() }, "Not yet"))));
    }

    if (m.counts) {
      const c = m.counts;
      body.append(h("div", { class: "chips" },
        h("span", { class: "chip" }, `${c.detected} fields`),
        h("span", { class: "chip ok" }, `${c.complete} complete`),
        c.needs_review ? h("span", { class: "chip warn" }, `${c.needs_review} to review`) : null,
        c.missing_required ? h("span", { class: "chip bad" }, `${c.missing_required} missing`) : null,
        c.user_action_required ? h("span", { class: "chip warn" }, `${c.user_action_required} for you`) : null,
        c.failed_to_fill ? h("span", { class: "chip bad" }, `${c.failed_to_fill} failed`) : null));
    }
    if (m.noFields) body.append(h("div", { class: "banner" }, "No form fields were found on this page. If the application opens in a new step or a frame, continue to it and press Rescan."));

    const bulk = m.ready.filter((r) => !r.sensitive);
    const row = h("div", { class: "row" });
    if (m.mode !== "MANUAL_ASSIST") {
      row.append(h("button", { class: "pri", disabled: !bulk.length || !!m.resume?.blocked && bulk.every((r) => r.action === "attach"), onclick: () => this.act.fillReady() },
        bulk.length ? `Fill ${bulk.length} ready field${bulk.length === 1 ? "" : "s"}` : "Nothing ready to fill"));
    }
    row.append(h("button", { onclick: () => this.act.rescan() }, "Rescan page"),
      h("button", { disabled: !m.canUndo, onclick: () => this.act.undo() }, "Undo last fill"));
    body.append(row);

    for (const e of m.addEntries) {
      const noun = ({ experience: "work experience", education: "education", certification: "certification", language: "language" } as Record<string, string>)[e.name] ?? e.name;
      body.append(h("div", { class: "banner" }, `Your resume has ${e.want} ${noun} entr${e.want === 1 ? "y" : "ies"}; this page shows ${e.have}.`,
        h("div", { class: "row" }, h("button", { onclick: () => this.act.addEntries(e.name) }, `Add ${e.want - e.have} more`))));
    }

    if (m.attention.length) {
      body.append(h("h4", { class: "sec" }, `Needs your attention (${m.attention.length})`));
      for (const it of m.attention) body.append(this.attentionCard(it, m));
    } else if (m.counts && m.counts.detected) {
      body.append(h("div", { class: "banner" }, "Nothing needs your attention on this page right now."));
    }

    if (m.ready.length) {
      const det = h("details", {}, h("summary", {}, `Ready to fill (${m.ready.length})`));
      const ul = h("ul", {});
      for (const r of m.ready) {
        const li = h("li", {}, `${displayLabel(m.controls.get(r.key)?.d ?? ({ label: r.label } as any))}: `, h("span", { class: "val" }, r.action === "attach" ? (r.value || "resume") : (r.option?.label ?? r.value ?? "")));
        li.append(" ", h("span", { class: "tag" }, `${r.confidence}% · ${r.source.toLowerCase().replace(/_/g, " ")}`));
        if (r.sensitive || m.mode === "MANUAL_ASSIST") li.append(" ", h("button", { class: "ghost", onclick: () => this.act.fillKey(r.key, false) }, "Insert"));
        ul.append(li);
      }
      det.append(ul);
      body.append(det);
    }

    body.append(h("div", { class: "row" }, h("button", { onclick: () => this.act.finalReview() }, "Final review checklist")));
    if (m.final) body.append(this.finalBox(m.final));
  }

  private embeddedBanner(m: PanelModel): HTMLElement {
    return h("div", { class: "banner warn" }, `This page embeds a ${m.embeddedAts} application in a frame. The agent can only read pages it is running on, so open the application on its own page and start there.`,
      h("div", { class: "row" }, h("button", { onclick: () => this.act.openEmbedded() }, "Open it in a new tab")));
  }

  private resumeBanner(rs: ResumeState): HTMLElement {
    const box = h("div", { class: "banner bad" }, h("b", {}, "Choose a resume"), h("div", {}, rs.blocked || ""));
    const row = h("div", { class: "row" });
    if (rs.expected && !/missing or has changed|was deleted/.test(rs.blocked || "")) {
      row.append(h("button", { onclick: () => this.act.chooseResume(rs.expected!.id) }, `Keep ${rs.expected.filename}`));
    }
    if (rs.current && rs.current.id !== rs.expected?.id) row.append(h("button", { class: "pri", onclick: () => this.act.chooseResume(rs.current!.id) }, `Use ${rs.current.filename}`));
    box.append(row);
    return box;
  }

  private finalBox(f: NonNullable<PanelModel["final"]>): HTMLElement {
    const box = h("div", { class: `banner ${f.ready ? "" : "warn"}` }, h("b", {}, f.headline));
    const ul = h("ul", { class: "plain" });
    for (const c of f.checks) ul.append(h("li", { class: `ck ${c.ok ? "ok" : "bad"}` }, h("span", {}, c.ok ? "✓" : "✗"), h("span", {}, c.label + (c.detail ? `: ${c.detail}` : ""))));
    box.append(ul, h("div", { class: "tag" }, f.note));
    return box;
  }

  private attentionCard(it: AttentionItem, m: PanelModel): HTMLElement {
    const c = m.controls.get(it.key);
    const r = m.results.get(it.key);
    const label = it.label || (c ? displayLabel(c.d) : "Unlabeled field");
    const card = h("div", { class: "card" });
    card.append(h("h4", {}, label, it.required ? h("span", { class: "req" }, " *") : null, it.sensitive ? h("span", { class: "tag" }, "  sensitive") : null));
    if (it.reason) card.append(h("div", { class: "why" }, it.reason));
    const show = h("button", { class: "ghost", onclick: () => this.act.show(it.key) }, "Show on page");

    if (it.action === "conflict" && it.conflict) {
      const cf = it.conflict;
      const custom = h("input", { type: "text", placeholder: "Or type the correct value" });
      card.append(
        h("div", {}, "Profile: ", h("span", { class: "val" }, cf.profile_value)), h("div", {}, "Resume: ", h("span", { class: "val" }, cf.resume_value)),
        h("div", { class: "row" },
          h("button", { onclick: () => this.act.resolveConflict(cf.canonical_field, "profile") }, "Use profile"),
          h("button", { onclick: () => this.act.resolveConflict(cf.canonical_field, "resume") }, "Use resume")),
        custom, h("button", { onclick: () => custom.value.trim() && this.act.resolveConflict(cf.canonical_field, "custom", custom.value.trim()) }, "Use typed value"), show);
      return card;
    }

    if (it.action === "user_action") { card.append(h("div", { class: "tag" }, "Only you can do this one."), show); return card; }

    if ((it.action === "review" || it.action === "confirm") && (it.suggestion || r?.value)) {
      const val = r?.option?.label ?? it.suggestion ?? r?.value ?? "";
      card.append(h("div", {}, "Proposed: ", h("span", { class: "val" }, val)), h("div", { class: "tag" }, r ? `${r.confidence}% confidence · ${r.source.toLowerCase().replace(/_/g, " ")}` : ""));
      card.append(h("div", { class: "row" },
        h("button", { class: "pri", onclick: () => this.act.fillKey(it.key, true) }, it.action === "confirm" ? "Use anyway" : "Use this"),
        h("button", { onclick: () => { this.drafts.set(it.key, val); this.render(m); } }, "Edit"), show));
      if (this.drafts.has(it.key)) card.append(...this.answerBox(it, c, m, this.drafts.get(it.key)!));
      return card;
    }

    if (it.status === "FAILED_TO_FILL") {
      card.append(h("div", { class: "row" }, h("button", { onclick: () => this.act.fillKey(it.key, true) }, "Retry"), show));
      card.append(...this.answerBox(it, c, m, ""));
      return card;
    }

    card.append(...this.answerBox(it, c, m, it.suggestion || ""), h("div", { class: "row" }, show));
    return card;
  }

  private answerBox(it: AttentionItem, c: Control | undefined, m: PanelModel, initial: string): Node[] {
    const draft = this.drafts.get(it.key) ?? initial;
    const opts = c?.d.options.filter((o) => (o.label || o.value).trim() && !/^(select|choose|--)/i.test(o.label)) ?? [];
    const useSelect = !!c && opts.length > 0 && (c.d.kind === "select" || c.d.kind === "radio_group" || c.d.kind === "custom_select" && opts.length > 0);
    let input: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;
    if (useSelect) {
      input = h("select", {}, h("option", { value: "" }, "Choose…"), ...opts.map((o) => h("option", { value: o.label || o.value }, o.label || o.value)));
      (input as HTMLSelectElement).value = opts.some((o) => (o.label || o.value) === draft) ? draft : "";
    } else if (c?.d.kind === "textarea" || (it.suggestion || "").length > 80 || /why|describe|tell us|explain/i.test(it.label || "")) {
      input = h("textarea", { value: draft, placeholder: "Your answer" });
    } else {
      input = h("input", { type: "text", value: draft, placeholder: "Your answer" });
    }
    input.addEventListener("input", () => this.drafts.set(it.key, input.value));
    const remember = h("input", { type: "checkbox" });
    const canRemember = !it.sensitive && !!it.label;
    const save = () => {
      const v = input.value.trim();
      if (!v) return;
      this.drafts.delete(it.key);
      this.act.saveAnswer(it.key, v, remember.checked);
    };
    const nodes: Node[] = [];
    if (it.suggestion && !draft) nodes.push(h("div", { class: "tag" }, "Suggested: " + it.suggestion));
    nodes.push(input);
    if (canRemember) nodes.push(h("label", { class: "chk" }, remember, "Remember this answer for similar questions"));
    nodes.push(h("div", { class: "row" }, h("button", { class: "pri", onclick: save }, "Use for this application")));
    return nodes;
  }
}
