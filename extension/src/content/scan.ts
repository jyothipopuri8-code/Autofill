// Find every form control on the page and describe it for the agent (doc §12). Radio/checkbox groups are
// reported as one field. Open shadow roots are searched; closed ones and cross-origin iframes are not.
import type { FieldDescriptor, Kind, Option } from "../shared/types";
import type { Adapter } from "./adapters/base";
import { cleanLabel, collapse, hash, isVisible, norm, ownText } from "./dom";
import { labelInfo, looksRequired, optionLabel } from "./labels";
import { OwnershipTracker } from "./ownership";
import { assignSections, HEADING_SELECTOR, isHeadingEl } from "./sections";

export const HOST_ATTR = "data-autofill-agent";

export interface Control {
  key: string;
  d: FieldDescriptor;
  /** The control itself; for groups, the first member. */
  el: HTMLElement;
  /** Radio/checkbox/role=radio members of a group. */
  members: HTMLElement[];
}

export interface ScanResult {
  controls: Control[];
  byKey: Map<string, Control>;
}

const CONTROL_SEL = [
  "input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=image]):not([type=reset])",
  "select", "textarea",
  "[role=combobox]:not(input):not(select)",
  "button[aria-haspopup=listbox]",
  "[role=radiogroup]",
].join(",");

const CAPTCHA_SEL = "iframe[src*='recaptcha'],iframe[src*='hcaptcha'],iframe[src*='turnstile'],iframe[src*='captcha'],.g-recaptcha,.h-captcha,.cf-turnstile,[data-sitekey]";
const PLACEHOLDER_TEXT = /^(select|choose|please select|pick|--+|—+|…|\.\.\.)/i;

/** querySelectorAll that also looks inside open shadow roots, in document order. */
export function deepAll(root: ParentNode, selector: string): HTMLElement[] {
  const out: HTMLElement[] = [];
  const walk = (node: ParentNode) => {
    for (const el of Array.from(node.querySelectorAll<HTMLElement>("*"))) {
      if (el.matches(selector)) out.push(el);
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(root);
  return out;
}

function inOwnUi(el: Element): boolean {
  return !!el.closest(`[${HOST_ATTR}]`);
}

function rawLabelText(el: HTMLElement): string {
  const parts: string[] = [];
  const labels = (el as HTMLInputElement).labels;
  if (labels) for (const l of Array.from(labels)) parts.push(l.textContent || "");
  const wrap = el.closest("label");
  if (wrap) parts.push(wrap.textContent || "");
  const fs = el.closest("fieldset")?.querySelector(":scope > legend");
  if (fs) parts.push(fs.textContent || "");
  const lb = el.getAttribute("aria-labelledby");
  if (lb) for (const id of lb.split(/\s+/)) parts.push(el.ownerDocument.getElementById(id)?.textContent || "");
  parts.push(el.getAttribute("aria-label") || "");
  return parts.join(" ");
}

function controlVisible(el: HTMLElement): boolean {
  if (isVisible(el)) return true;
  const type = (el as HTMLInputElement).type;
  if (type === "radio" || type === "checkbox" || type === "file") {
    const labels = (el as HTMLInputElement).labels;
    if (labels && Array.from(labels).some((l) => isVisible(l))) return true;
    let p: HTMLElement | null = el.parentElement;
    for (let i = 0; p && i < 3; i++, p = p.parentElement) if (isVisible(p) && p.getClientRects().length) return true;
  }
  return false;
}

function selectOptions(sel: HTMLSelectElement): Option[] {
  return Array.from(sel.options).map((o) => ({ value: o.value, label: collapse(o.label || o.textContent, 200) }));
}

function selectCurrent(sel: HTMLSelectElement): string {
  const o = sel.selectedOptions[0];
  if (!o) return "";
  if (!o.value && sel.selectedIndex <= 0) return "";
  const label = collapse(o.label || o.textContent, 200);
  return PLACEHOLDER_TEXT.test(label) && sel.selectedIndex <= 0 ? "" : label;
}

export function customCurrent(el: HTMLElement): string {
  if (el instanceof HTMLInputElement) {
    if (el.value) return collapse(el.value, 300);
    // react-select style: the chosen value is rendered as text next to the (empty) input.
    for (let p: HTMLElement | null = el.parentElement, i = 0; p && i < 3; p = p.parentElement, i++) {
      const sv = p.querySelector("[class*='singleValue' i],[class*='single-value' i],[class*='selected-value' i]");
      if (sv && sv.textContent) return collapse(sv.textContent, 300);
    }
    // Otherwise whatever text the control shows besides its placeholder and open menu.
    const ctl = el.closest("[class*='control' i]") ?? el.parentElement;
    if (ctl) {
      const clone = ctl.cloneNode(true) as HTMLElement;
      clone.querySelectorAll("input,select,button,svg,[role=listbox],[class*='placeholder' i]").forEach((n) => n.remove());
      const t = collapse(clone.textContent, 300);
      if (t && !PLACEHOLDER_TEXT.test(t)) return t;
    }
    return "";
  }
  const t = collapse(el.getAttribute("aria-valuetext") || el.textContent, 300);
  return !t || PLACEHOLDER_TEXT.test(t) ? "" : t;
}

export class Scanner {
  /** Options read from custom dropdowns the first time we had to open them (keyed by field key). */
  harvested = new Map<string, Option[]>();

  constructor(private adapter: Adapter, private tracker: OwnershipTracker) {}

  scan(doc: Document): ScanResult {
    const els = [...deepAll(doc, CONTROL_SEL), ...this.adapter.extraControls(doc)]
      .filter((e, i, a) => a.indexOf(e) === i && !inOwnUi(e));

    const controls: Control[] = [];
    const entryByEl = new Map<HTMLElement, FieldDescriptor>();
    const keyCount = new Map<string, number>();
    const groupDone = new Set<string>();

    const addControl = (el: HTMLElement, d: FieldDescriptor, members: HTMLElement[] = []) => {
      const base = `${d.kind}|${d.id || d.name || hash(norm(d.label || d.legend || d.nearby_text || d.placeholder || ""))}`;
      const n = keyCount.get(base) ?? 0;
      keyCount.set(base, n + 1);
      d.key = n ? `${base}#${n}` : base;
      if (d.kind === "custom_select" && !d.options.length) {
        const known = this.harvested.get(d.key);
        if (known) d.options = known;
      }
      this.adapter.decorate(el, d);
      controls.push({ key: d.key, d, el, members });
      entryByEl.set(el, d);
    };

    for (const el of els) {
      const tag = el.tagName;
      const role = el.getAttribute("role");

      if (role === "radiogroup") {
        const radios = Array.from(el.querySelectorAll<HTMLElement>("[role=radio]"));
        if (radios.length < 2 || el.querySelector("input[type=radio]")) continue;
        addControl(radios[0], this.roleRadioGroup(el, radios), radios);
        continue;
      }

      if (tag === "INPUT") {
        const input = el as HTMLInputElement;
        const type = (input.type || "text").toLowerCase();
        if (el.closest("[role=search]") || type === "search" && !el.closest("form")) continue;
        if (type === "radio") {
          const gk = this.groupKey(input);
          if (groupDone.has(gk)) continue;
          groupDone.add(gk);
          const members = els.filter((e): e is HTMLInputElement => e instanceof HTMLInputElement && e.type === "radio" && this.groupKey(e) === gk);
          addControl(members[0], this.inputGroup(members, "radio_group"), members);
          continue;
        }
        if (type === "checkbox") {
          const gk = this.groupKey(input);
          const members = input.name
            ? els.filter((e): e is HTMLInputElement => e instanceof HTMLInputElement && e.type === "checkbox" && this.groupKey(e) === gk)
            : [input];
          if (members.length > 1) {
            if (groupDone.has(gk)) continue;
            groupDone.add(gk);
            addControl(members[0], this.inputGroup(members, "checkbox_group"), members);
          } else {
            addControl(input, this.single(input, "checkbox"));
          }
          continue;
        }
        if (type === "file") { addControl(input, this.single(input, "file")); continue; }
        if (input.getAttribute("role") === "combobox") { addControl(input, this.single(input, "custom_select")); continue; }
        addControl(input, this.single(input, this.inputKind(type, input)));
        continue;
      }

      if (tag === "SELECT") { addControl(el, this.single(el, "select")); continue; }
      if (tag === "TEXTAREA") { addControl(el, this.single(el, "textarea")); continue; }
      // [role=combobox] divs/buttons and button[aria-haspopup=listbox]
      addControl(el, this.single(el, "custom_select"));
    }

    // CAPTCHA widgets: reported so the agent can ask the user to complete them (doc §36).
    let n = 0;
    for (const cap of deepAll(doc, CAPTCHA_SEL).filter((e) => !inOwnUi(e) && (e.tagName === "IFRAME" || !e.querySelector(CAPTCHA_SEL)))) {
      const d = this.blank("captcha", cap);
      d.label = "CAPTCHA";
      d.key = `captcha|${n++}`;
      d.visible = isVisible(cap);
      controls.push({ key: d.key, d, el: cap, members: [] });
      entryByEl.set(cap, d);
    }

    // Sections need headings and fields in document order.
    const orderEls = deepAll(doc, `${HEADING_SELECTOR},${CONTROL_SEL},[role=radio]`).filter((e) => !inOwnUi(e));
    const order: HTMLElement[] = [];
    for (const e of orderEls) {
      if (entryByEl.has(e) || (isHeadingEl(e) && !entryByEl.has(e))) order.push(e);
    }
    // Group members other than the first are not entries, so route them through the first member.
    assignSections(order, entryByEl, (e) => this.adapter.sectionOf(e));

    const byKey = new Map(controls.map((c) => [c.key, c]));
    return { controls, byKey };
  }

  // --- descriptors -------------------------------------------------------------

  private blank(kind: Kind, el: HTMLElement): FieldDescriptor {
    const input = el as HTMLInputElement;
    return {
      key: "", kind, label: null, name: input.name || el.getAttribute("name") || null, id: el.id || null, placeholder: null,
      aria_label: null, autocomplete: el.getAttribute("autocomplete"), input_type: input.type || null, nearby_text: null,
      legend: null, options: [], required: false, current_value: null, ownership: "EMPTY", section: null,
      date_format: el.getAttribute("data-date-format") || el.getAttribute("data-format"),
      maxlength: Number.isInteger(input.maxLength) && input.maxLength >= 0 ? input.maxLength : null,
      visible: true, disabled: false,
    };
  }

  private inputKind(type: string, el: HTMLInputElement): Kind {
    switch (type) {
      case "email": return "email";
      case "tel": return "tel";
      case "number": return "number";
      case "url": return "url";
      case "password": return "password";
      case "date": return "date";
      case "month": return "month_year";
      case "text": case "search": case "": return el.hasAttribute("list") ? "autocomplete" : "text";
      default: return "unknown";
    }
  }

  private single(el: HTMLElement, kind: Kind): FieldDescriptor {
    const d = this.blank(kind, el);
    const info = labelInfo(el);
    d.label = info.label; d.aria_label = info.aria_label; d.legend = info.legend; d.nearby_text = info.nearby_text; d.placeholder = info.placeholder;
    d.required = looksRequired(el, rawLabelText(el));
    d.visible = controlVisible(el);
    d.disabled = (el as HTMLInputElement).disabled === true || el.getAttribute("aria-disabled") === "true" || (el as HTMLInputElement).readOnly === true && kind !== "custom_select";
    if (el instanceof HTMLSelectElement) {
      d.options = selectOptions(el);
      d.current_value = selectCurrent(el) || null;
    } else if (kind === "checkbox") {
      const lab = optionLabel(el as HTMLInputElement);
      d.label = d.label || lab || null;
      d.options = [{ value: (el as HTMLInputElement).value || "on", label: lab }];
      d.current_value = (el as HTMLInputElement).checked ? "true" : "false";
    } else if (kind === "custom_select") {
      d.current_value = customCurrent(el) || null;
    } else if (kind === "file") {
      d.current_value = (el as HTMLInputElement).files?.length ? (el as HTMLInputElement).files![0].name : null;
    } else {
      d.current_value = (el as HTMLInputElement).value || null;
    }
    this.setOwnership(el, d, kind === "checkbox" ? d.current_value === "true" : !!d.current_value);
    return d;
  }

  private groupKey(input: HTMLInputElement): string {
    const scope = input.form ? `${[...input.ownerDocument.forms].indexOf(input.form)}` : "-";
    if (input.name) return `${scope}|${input.type}|${input.name}`;
    const container = input.closest("fieldset,[role=radiogroup],[role=group]");
    return `${scope}|${input.type}|~${container ? hash(container.outerHTML.slice(0, 200)) : hash(input.id || String(Math.random()))}`;
  }

  private inputGroup(members: HTMLInputElement[], kind: "radio_group" | "checkbox_group"): FieldDescriptor {
    const first = members[0];
    const d = this.blank(kind, first);
    d.id = null; // an id belongs to one member, not the group
    d.autocomplete = null;
    const info = labelInfo(first, true);
    d.legend = info.legend;
    d.nearby_text = info.nearby_text;
    d.aria_label = null;
    d.label = info.legend || info.nearby_text || null;
    d.placeholder = null;
    d.options = members.map((m) => ({ value: m.value, label: optionLabel(m) }));
    d.required = members.some((m) => m.required || m.getAttribute("aria-required") === "true") || looksRequired(first, rawLabelText(first));
    d.visible = members.some(controlVisible);
    d.disabled = members.every((m) => m.disabled);
    const checked = members.filter((m) => m.checked).map((m) => optionLabel(m));
    d.current_value = checked.length ? checked.join(", ") : null;
    this.setOwnership(first, d, checked.length > 0, members);
    return d;
  }

  private roleRadioGroup(group: HTMLElement, radios: HTMLElement[]): FieldDescriptor {
    const d = this.blank("radio_group", group);
    d.id = null; d.name = null;
    d.legend = (group.getAttribute("aria-labelledby")
      ? ownText(group.ownerDocument.getElementById(group.getAttribute("aria-labelledby")!.split(/\s+/)[0]))
      : group.getAttribute("aria-label")) || null;
    d.nearby_text = labelInfo(radios[0], true).nearby_text;
    d.label = d.legend ? cleanLabel(d.legend) : d.nearby_text;
    d.options = radios.map((r) => ({ value: r.getAttribute("data-value") || r.getAttribute("value") || collapse(r.textContent, 100), label: collapse(r.textContent || r.getAttribute("aria-label"), 200) }));
    d.required = group.getAttribute("aria-required") === "true" || looksRequired(group, d.legend || "");
    d.visible = isVisible(group);
    const on = radios.filter((r) => r.getAttribute("aria-checked") === "true");
    d.current_value = on.length ? collapse(on[0].textContent, 200) : null;
    this.setOwnership(radios[0], d, on.length > 0, radios);
    return d;
  }

  private setOwnership(el: HTMLElement, d: FieldDescriptor, nonEmpty: boolean, members: HTMLElement[] = []): void {
    const tracked = [el, ...members].map((m) => this.tracker.get(m)).find((o) => o && o !== "EMPTY");
    d.ownership = tracked ?? (nonEmpty ? "SITE_DEFAULT" : "EMPTY");
    if (nonEmpty && (d.ownership === "EMPTY")) d.ownership = "SITE_DEFAULT";
  }
}

/** The text a human would read as this field's question, for panel display. */
export function displayLabel(d: FieldDescriptor): string {
  return d.label || d.legend || d.aria_label || d.nearby_text || d.placeholder || d.name || d.id || "Unlabeled field";
}
