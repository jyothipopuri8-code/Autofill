// Small DOM helpers shared by scanning and filling.

export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export function isVisible(el: Element): boolean {
  if (!(el instanceof HTMLElement)) return true;
  if (el.hidden || el.closest("[hidden],[aria-hidden='true']:not(body)")) return false;
  const cs = getComputedStyle(el);
  if (cs.display === "none" || cs.visibility === "hidden" || cs.visibility === "collapse") return false;
  if (el.closest("[style*='display: none'],[style*='display:none']")) return false;
  const r = el.getBoundingClientRect();
  if (!(r.width > 0 || r.height > 0 || el.getClientRects().length > 0)) return false;
  return !looksHidden(el, cs, r);
}

// Honeypots: fields a person can never see or reach (bots fill them, and employers use that to reject bots).
// A field like that must never be scanned, so it is never filled and never shown to the user as a question.
function looksHidden(el: HTMLElement, cs: CSSStyleDeclaration, r: DOMRect): boolean {
  for (let n: HTMLElement | null = el, i = 0; n && i < 12; n = n.parentElement, i++) {
    if (parseFloat(getComputedStyle(n).opacity) < 0.05) return true;
  }
  // Pushed far off-screen (text-indent / left:-9999px tricks), measured in document coordinates.
  const sx = window.scrollX, sy = window.scrollY;
  if (r.right + sx < -100 || r.bottom + sy < -100) return true;
  if (r.left + sx > document.documentElement.scrollWidth + 1000 || r.top + sy > document.documentElement.scrollHeight + 5000) return true;
  if (/^rect\(\s*0(px)?[ ,]+0(px)?[ ,]+0(px)?[ ,]+0(px)?\s*\)$/.test(cs.clip) || /inset\(\s*(50|100)%/.test(cs.clipPath)) return true;
  // A real text box is never a 1px dot. Radios, checkboxes and file inputs are often restyled that way, and are
  // judged by their label instead (see controlVisible in scan.ts).
  if (el instanceof HTMLInputElement) {
    if (!["radio", "checkbox", "file", "hidden", "submit", "button", "image", "reset"].includes(el.type) && (r.width <= 2 || r.height <= 2)) return true;
  } else if ((el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement) && (r.width <= 2 || r.height <= 2)) return true;
  return false;
}

export function collapse(s: string | null | undefined, max = 300): string {
  return (s ?? "").replace(/\s+/g, " ").trim().slice(0, max);
}

/** Remove "*" / "(required)" markers and trailing colons from a label. */
export function cleanLabel(s: string | null | undefined): string {
  return collapse(s, 600)
    .replace(/\(\s*required\s*\)/gi, "")
    .replace(/\brequired\b\s*$/i, "")
    .replace(/[*✱]/g, "")
    .replace(/\s*:\s*$/, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 300);
}

/** Text of an element without the text of form controls inside it. */
export function ownText(el: Element | null, max = 300): string {
  if (!el) return "";
  const clone = el.cloneNode(true) as Element;
  clone.querySelectorAll("input,select,textarea,button,script,style,svg,[aria-hidden='true']").forEach((n) => n.remove());
  return collapse(clone.textContent, max);
}

export async function waitFor<T>(fn: () => T | null | undefined | false, timeout = 2000, interval = 40): Promise<T | null> {
  const start = performance.now();
  for (;;) {
    const v = fn();
    if (v) return v as T;
    if (performance.now() - start > timeout) return null;
    await sleep(interval);
  }
}

type ValueEl = HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement;

/** Set a value the way a user's typing would, so React/Vue/Angular controlled inputs notice it. */
export function setNativeValue(el: ValueEl, value: string): void {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
    : el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  if (setter) setter.call(el, value);
  else el.value = value;
}

export function fire(el: Element, type: string, init: EventInit = {}): void {
  el.dispatchEvent(new Event(type, { bubbles: true, cancelable: true, ...init }));
}

export function fireInput(el: Element, data?: string): void {
  el.dispatchEvent(new InputEvent("input", { bubbles: true, cancelable: true, inputType: "insertText", data: data ?? null }));
}

export function norm(s: string | null | undefined): string {
  return (s ?? "").toLowerCase().replace(/[^a-z0-9+]+/g, " ").trim();
}

export function cssEscape(s: string): string {
  return typeof CSS !== "undefined" && CSS.escape ? CSS.escape(s) : s.replace(/([^\w-])/g, "\\$1");
}

export function hash(s: string): string {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
  return (h >>> 0).toString(36);
}

/** A full pointer/mouse click sequence, for widgets that open on mousedown rather than click. */
export function realClick(el: Element): void {
  const r = el.getBoundingClientRect();
  const init: MouseEventInit = { bubbles: true, cancelable: true, view: window, button: 0, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 };
  el.dispatchEvent(new PointerEvent("pointerdown", { ...init, pointerType: "mouse", isPrimary: true }));
  el.dispatchEvent(new MouseEvent("mousedown", init));
  el.dispatchEvent(new PointerEvent("pointerup", { ...init, pointerType: "mouse", isPrimary: true }));
  el.dispatchEvent(new MouseEvent("mouseup", init));
  el.dispatchEvent(new MouseEvent("click", init));
}

export function digits(s: string | null | undefined): string {
  return (s ?? "").replace(/\D+/g, "");
}
