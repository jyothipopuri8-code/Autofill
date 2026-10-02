// Put values into the page the way a person would, then check they stuck (doc §17, §20, §22, §28).
// Never clicks next/submit, never touches password or CAPTCHA fields, never overwrites what the user typed.
import type { FieldResult } from "../shared/types";
import { collapse, digits, fire, fireInput, norm, realClick, setNativeValue, sleep, waitFor } from "./dom";
import { OwnershipTracker, UndoEntry } from "./ownership";
import { Control, customCurrent } from "./scan";

export interface ResumeBlob { filename: string; mime: string; bytes: Uint8Array; sha256: string }

export interface FillEnv {
  tracker: OwnershipTracker;
  /** Fetches the application's resume from the agent; null when blocked. */
  resume: () => Promise<ResumeBlob | null>;
  /** The user explicitly approved replacing a value the site pre-filled. */
  overwriteSiteDefault?: boolean;
}

export interface FillOutcome {
  key: string;
  outcome: "FILLED" | "FAILED_TO_FILL" | "SKIPPED";
  value?: string;
  error?: string;
  undo?: UndoEntry;
}

const TEXTY = new Set(["text", "email", "tel", "number", "url", "textarea", "autocomplete", "date", "month_year", "unknown"]);

/** What the control currently holds, as one comparable string. */
export function readValue(c: Control): string {
  const { el, d } = c;
  switch (d.kind) {
    case "select": return (el as HTMLSelectElement).value;
    case "radio_group": {
      const on = c.members.find((m) => (m as HTMLInputElement).checked || m.getAttribute("aria-checked") === "true");
      return on ? ((on as HTMLInputElement).value ?? on.getAttribute("data-value") ?? collapse(on.textContent, 100)) : "";
    }
    case "checkbox": return (el as HTMLInputElement).checked ? "true" : "false";
    case "checkbox_group": return c.members.filter((m) => (m as HTMLInputElement).checked).map((m) => (m as HTMLInputElement).value).join(",");
    case "custom_select": return customCurrent(el);
    case "file": return (el as HTMLInputElement).files?.[0]?.name ?? "";
    default: return (el as HTMLInputElement).value ?? "";
  }
}

function same(kind: string, expected: string, actual: string): boolean {
  const e = expected.trim(), a = actual.trim();
  if (e === a) return true;
  if (norm(e) === norm(a)) return true;
  if (kind === "tel" || /^[\d\s()+.\-/]+$/.test(e)) return digits(e) === digits(a) && digits(e).length >= 4;
  return false;
}

// --- individual control types --------------------------------------------------------------

function writeText(el: HTMLInputElement | HTMLTextAreaElement, value: string): void {
  const focused = el.ownerDocument.activeElement === el;
  if (!focused) el.focus({ preventScroll: true });
  setNativeValue(el, value);
  fireInput(el, value);
  fire(el, "change");
  if (!focused) { el.blur(); }
}

async function fillText(c: Control, value: string): Promise<boolean> {
  const el = c.el as HTMLInputElement | HTMLTextAreaElement;
  writeText(el, value);
  await sleep(30);
  if (same(c.d.kind, value, el.value)) return true;
  // Fallback: simulate typing through the editing pipeline (some masked inputs only accept this).
  el.focus({ preventScroll: true });
  try { el.select(); el.ownerDocument.execCommand("insertText", false, value); } catch { /* ignore */ }
  await sleep(30);
  return same(c.d.kind, value, el.value);
}

function fillSelect(c: Control, r: FieldResult): boolean {
  const el = c.el as HTMLSelectElement;
  const want = r.option ?? (r.value ? { value: r.value, label: r.value } : null);
  if (!want) return false;
  const opts = Array.from(el.options);
  const hit = opts.find((o) => o.value === want.value && collapse(o.label || o.textContent) === want.label)
    ?? opts.find((o) => o.value === want.value && want.value !== "")
    ?? opts.find((o) => norm(o.label || o.textContent) === norm(want.label));
  if (!hit) return false;
  el.focus({ preventScroll: true });
  setNativeValue(el, hit.value);
  fireInput(el);
  fire(el, "change");
  return el.value === hit.value;
}

function fillRadio(c: Control, r: FieldResult): boolean {
  const want = r.option;
  if (!want) return false;
  const label = (m: HTMLElement) => norm(m instanceof HTMLInputElement ? optionLabelOf(m) : m.getAttribute("aria-label") || m.textContent);
  const byValue = c.members.filter((m) => m instanceof HTMLInputElement && m.value !== "" && m.value === want.value);
  const hit = byValue.length === 1 ? byValue[0] : c.members.find((m) => label(m) === norm(want.label));
  if (!hit) return false;
  if (hit instanceof HTMLInputElement) {
    if (!hit.checked) hit.click();
    return hit.checked;
  }
  if (hit.getAttribute("aria-checked") !== "true") hit.click();
  return hit.getAttribute("aria-checked") === "true";
}

function optionLabelOf(m: HTMLInputElement): string {
  const l = m.labels?.[0];
  return collapse(l?.textContent || m.nextSibling?.textContent || m.value, 200);
}

function fillCheckbox(c: Control, r: FieldResult): boolean {
  const el = c.el as HTMLInputElement;
  const want = r.checked ?? (r.value ? /^(yes|true|on|1)$/i.test(r.value) : null);
  if (want === null) return false;
  if (el.checked !== want) el.click();
  return el.checked === want;
}

function fillCheckboxGroup(c: Control, r: FieldResult): boolean {
  const wanted = (r.option ? [r.option.value] : (r.value || "").split(/\s*[,;]\s*/)).filter(Boolean);
  if (!wanted.length) return false;
  let ok = true;
  for (const w of wanted) {
    const hit = c.members.find((m) => (m as HTMLInputElement).value === w) as HTMLInputElement | undefined
      ?? c.members.find((m) => norm(optionLabelOf(m as HTMLInputElement)) === norm(w)) as HTMLInputElement | undefined;
    if (!hit) { ok = false; continue; }
    if (!hit.checked) hit.click();
    ok = ok && hit.checked;
  }
  return ok;
}

function visibleOptions(doc: Document, el: HTMLElement): HTMLElement[] {
  const ctl = el.getAttribute("aria-controls") || el.getAttribute("aria-owns");
  const scope = ctl ? doc.getElementById(ctl) : null;
  const pool = Array.from((scope ?? doc).querySelectorAll<HTMLElement>("[role=option],[role=menuitem],li[data-value],[class*='option' i][tabindex],[class*='option' i][role]"));
  return pool.filter((o) => o.getClientRects().length > 0 && getComputedStyle(o).visibility !== "hidden");
}

async function fillCustomSelect(c: Control, r: FieldResult): Promise<{ ok: boolean; error?: string }> {
  const el = c.el;
  const doc = el.ownerDocument;
  const target = collapse(r.option?.label ?? r.value ?? "", 300);
  if (!target) return { ok: false, error: "No value to choose" };
  const isInput = el instanceof HTMLInputElement;

  el.focus({ preventScroll: true });
  realClick(el);
  if (isInput) {
    setNativeValue(el as HTMLInputElement, target);
    fireInput(el, target);
  } else {
    el.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
  }
  const options = await waitFor(() => { const o = visibleOptions(doc, el); return o.length ? o : null; }, 2500);
  if (!options) { close(el); return { ok: false, error: "The dropdown did not show any options" }; }
  await sleep(80); // let a filtered list settle

  const live = visibleOptions(doc, el);
  const text = (o: HTMLElement) => norm(o.textContent);
  const t = norm(target);
  let hit = live.filter((o) => text(o) === t);
  if (hit.length !== 1) hit = hit.length ? hit : live.filter((o) => text(o).startsWith(t));
  if (hit.length !== 1) {
    close(el);
    return { ok: false, error: hit.length > 1 ? `Several options match "${target}"` : `No option matches "${target}"` };
  }
  realClick(hit[0]);
  await sleep(60);
  const now = norm(customCurrent(el));
  // Some widgets show the choice in a sibling element we cannot see; the dropdown closing is the second signal.
  const closed = !visibleOptions(doc, el).length;
  if (now === t || (now && now.includes(t)) || (closed && (!now || now === t))) return { ok: true };
  close(el);
  return { ok: false, error: "The dropdown did not keep the selection" };
}

function close(el: HTMLElement): void {
  el.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  if (el instanceof HTMLInputElement && el.value) { setNativeValue(el, ""); fireInput(el); }
  el.blur();
}

async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", bytes as unknown as BufferSource);
  return Array.from(new Uint8Array(d)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function attachResume(c: Control, env: FillEnv, expectedSha: string | null): Promise<{ ok: boolean; error?: string; name?: string }> {
  const blob = await env.resume();
  if (!blob) return { ok: false, error: "The agent did not provide the resume (it may be missing or blocked)" };
  if (expectedSha && blob.sha256 !== expectedSha) return { ok: false, error: "The resume file does not match the one chosen for this application" };
  if ((await sha256Hex(blob.bytes)) !== blob.sha256) return { ok: false, error: "The downloaded resume failed its integrity check" };
  const input = c.el as HTMLInputElement;
  const file = new File([blob.bytes as unknown as BlobPart], blob.filename, { type: blob.mime, lastModified: Date.now() });
  const dt = new DataTransfer();
  dt.items.add(file);
  input.files = dt.files;
  fireInput(input);
  fire(input, "change");
  await sleep(60);
  const got = input.files?.[0];
  if (!got || got.name !== blob.filename) return { ok: false, error: "The page did not accept the file" };
  if ((await sha256Hex(new Uint8Array(await got.arrayBuffer()))) !== blob.sha256) return { ok: false, error: "Attached file failed verification" };
  return { ok: true, name: blob.filename };
}

// --- entry point ---------------------------------------------------------------------------

/**
 * Fill one control from an engine result. The result's action decides whether this is allowed at all;
 * callers only pass results the user (or the active mode) approved.
 */
export async function fillControl(c: Control, r: FieldResult, env: FillEnv, expectedResumeSha: string | null): Promise<FillOutcome> {
  const key = c.key;
  const fail = (error: string): FillOutcome => ({ key, outcome: "FAILED_TO_FILL", error });
  const skip = (error: string): FillOutcome => ({ key, outcome: "SKIPPED", error });

  const kind = c.d.kind;
  if (kind === "password" || kind === "captcha") return skip("Left for you");
  if (!c.el.isConnected) return fail("The field disappeared from the page");
  if ((c.el as HTMLInputElement).disabled || c.el.getAttribute("aria-disabled") === "true") return skip("Field is disabled");
  if (r.action !== "fill" && r.action !== "review" && r.action !== "attach" && r.action !== "confirm" && r.action !== "keep") return skip("Nothing to fill");
  if (r.action === "keep") return { key, outcome: "FILLED", value: readValue(c) };

  // Manual-input protection (doc §27): anything the user touched, or that holds a value the agent did not put there.
  const owner = env.tracker.get(c.el) ?? c.members.map((m) => env.tracker.get(m)).find(Boolean);
  if (owner === "USER_FILLED" || owner === "USER_MODIFIED_AGENT_VALUE") return skip("You already changed this field");
  const before = readValue(c);
  const hadValue = kind === "checkbox" ? false : before !== "";
  if (hadValue && owner !== "AGENT_FILLED" && !env.overwriteSiteDefault && kind !== "file") return skip("The page already has a value here");

  env.tracker.busy = true;
  try {
    let ok = false;
    let error: string | undefined;
    if (kind === "file") {
      if (r.action !== "attach" && r.action !== "fill") return skip("Upload this file yourself");
      const res = await attachResume(c, env, expectedResumeSha);
      ok = res.ok; error = res.error;
    } else if (r.value === null && r.option === null && r.checked === null) {
      return skip("No value to enter");
    } else if (TEXTY.has(kind)) {
      ok = await fillText(c, r.value ?? "");
      if (!ok) error = "The page did not keep the value";
    } else if (kind === "select") {
      ok = fillSelect(c, r);
      if (!ok) error = "No matching option in the list";
    } else if (kind === "radio_group") {
      ok = fillRadio(c, r);
      if (!ok) error = "Could not select that option";
    } else if (kind === "checkbox") {
      ok = fillCheckbox(c, r);
      if (!ok) error = "Could not set the checkbox";
    } else if (kind === "checkbox_group") {
      ok = fillCheckboxGroup(c, r);
      if (!ok) error = "Could not tick the option(s)";
    } else if (kind === "custom_select") {
      const res = await fillCustomSelect(c, r);
      ok = res.ok; error = res.error;
    } else {
      return skip("This kind of field is not filled automatically");
    }
    if (!ok) return fail(error || "Could not fill");

    const after = readValue(c);
    env.tracker.markAgent(c.el, after);
    for (const m of c.members) env.tracker.markAgent(m, after);
    const undo: UndoEntry = {
      key, kind, previous: before, next: after, ts: Date.now(), source: r.source,
      current: () => readValue(c),
      restore: () => restore(c, before, env.tracker),
    };
    return { key, outcome: "FILLED", value: kind === "file" ? after : (r.option?.label ?? r.value ?? after), undo };
  } catch (e) {
    return fail(e instanceof Error ? e.message : "Unexpected error");
  } finally {
    env.tracker.busy = false;
  }
}

async function restore(c: Control, previous: string, tracker: OwnershipTracker): Promise<boolean> {
  tracker.busy = true;
  try {
    const { el, d } = c;
    switch (d.kind) {
      case "radio_group": {
        // Radios cannot be unchecked directly; restore a previously checked member, otherwise report that we could not.
        const prev = c.members.find((m) => (m as HTMLInputElement).value === previous);
        if (previous && prev) { (prev as HTMLInputElement).click(); return true; }
        return false;
      }
      case "checkbox": {
        const want = previous === "true";
        if ((el as HTMLInputElement).checked !== want) (el as HTMLInputElement).click();
        break;
      }
      case "checkbox_group": {
        const prevSet = new Set(previous.split(",").filter(Boolean));
        for (const m of c.members as HTMLInputElement[]) if (m.checked !== prevSet.has(m.value)) m.click();
        break;
      }
      case "file": {
        const input = el as HTMLInputElement;
        input.value = "";
        fire(input, "change");
        break;
      }
      case "custom_select":
        return false; // custom dropdowns have no reliable "clear"; the panel tells the user
      case "select":
        setNativeValue(el as HTMLSelectElement, previous); fireInput(el); fire(el, "change");
        break;
      default:
        setNativeValue(el as HTMLInputElement, previous); fireInput(el, previous); fire(el, "change");
    }
    tracker.release(el);
    for (const m of c.members) tracker.release(m);
    return true;
  } finally {
    tracker.busy = false;
  }
}
