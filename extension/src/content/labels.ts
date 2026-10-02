// Everything a control tells us about what it is (doc §12): label, aria, legend, nearby text, placeholder.
import { cleanLabel, collapse, ownText } from "./dom";

export interface LabelInfo {
  label: string | null;
  aria_label: string | null;
  legend: string | null;
  nearby_text: string | null;
  placeholder: string | null;
}

function byIds(ids: string | null, doc: Document): string {
  if (!ids) return "";
  return ids.split(/\s+/).map((id) => ownText(doc.getElementById(id))).filter(Boolean).join(" ");
}

export function explicitLabel(el: HTMLElement): string {
  const doc = el.ownerDocument;
  const labelled = byIds(el.getAttribute("aria-labelledby"), doc);
  if (labelled) return cleanLabel(labelled);
  const labels = (el as HTMLInputElement).labels;
  if (labels && labels.length) {
    for (const l of Array.from(labels)) {
      const t = ownText(l);
      if (t) return cleanLabel(t);
    }
  }
  const wrap = el.closest("label");
  if (wrap) {
    const t = ownText(wrap);
    if (t) return cleanLabel(t);
  }
  return "";
}

/** Question text for a group (radio/checkbox): fieldset legend, ARIA group label, or a heading-like text just before it. */
export function groupLegend(el: HTMLElement): string {
  const doc = el.ownerDocument;
  const fs = el.closest("fieldset");
  const legend = fs?.querySelector(":scope > legend");
  if (legend) {
    const t = ownText(legend);
    if (t) return cleanLabel(t);
  }
  const grp = el.closest("[role='radiogroup'],[role='group'],[role='checkboxgroup']");
  if (grp) {
    const t = byIds(grp.getAttribute("aria-labelledby"), doc) || grp.getAttribute("aria-label") || "";
    if (t) return cleanLabel(t);
  }
  return "";
}

/** Text of the closest preceding label-like element, for controls with no real <label>. */
export function nearbyText(el: HTMLElement): string {
  let node: HTMLElement | null = el;
  for (let depth = 0; node && depth < 4; depth++, node = node.parentElement) {
    let prev = node.previousElementSibling as HTMLElement | null;
    for (let hops = 0; prev && hops < 2; hops++, prev = prev.previousElementSibling as HTMLElement | null) {
      if (prev.matches("input,select,textarea,button,script,style")) continue;
      if (prev.querySelector("input,select,textarea") && !prev.matches("label")) continue;
      const t = ownText(prev, 400);
      if (t) return cleanLabel(t);
    }
    // A label-ish child of the wrapper that precedes the control inside the wrapper.
    const parent: HTMLElement | null = node.parentElement;
    if (parent) {
      const lab: Element | null = parent.querySelector(":scope > label, :scope > legend, :scope > [class*='label' i], :scope > span, :scope > p");
      if (lab && lab !== node && !lab.contains(el)) {
        const t = ownText(lab, 400);
        if (t) return cleanLabel(t);
      }
    }
  }
  return "";
}

export function labelInfo(el: HTMLElement, isGroupMember = false): LabelInfo {
  const aria = el.getAttribute("aria-label");
  const legend = groupLegend(el);
  let label = isGroupMember ? "" : explicitLabel(el);
  const placeholder = (el as HTMLInputElement).placeholder || el.getAttribute("data-placeholder") || null;
  let nearby = "";
  if (!label && !aria && !legend) nearby = nearbyText(el);
  else if (isGroupMember || !label) nearby = nearbyText(el);
  if (!label && aria) label = cleanLabel(aria);
  return {
    label: label || null,
    aria_label: aria ? cleanLabel(aria) : null,
    legend: legend || null,
    nearby_text: nearby ? collapse(nearby, 500) : null,
    placeholder: placeholder ? collapse(placeholder, 200) : null,
  };
}

/** Label text of one radio/checkbox option. */
export function optionLabel(el: HTMLInputElement): string {
  const own = explicitLabel(el);
  if (own) return own;
  const next = el.nextSibling;
  if (next && next.nodeType === Node.TEXT_NODE && collapse(next.textContent)) return cleanLabel(next.textContent);
  const sib = el.nextElementSibling;
  if (sib && !sib.matches("input,select,textarea")) {
    const t = ownText(sib);
    if (t) return cleanLabel(t);
  }
  return cleanLabel(el.value);
}

export function looksRequired(el: HTMLElement, rawLabelText: string): boolean {
  if ((el as HTMLInputElement).required) return true;
  if (el.getAttribute("aria-required") === "true") return true;
  if (el.hasAttribute("data-required") && el.getAttribute("data-required") !== "false") return true;
  return /[*✱]|\(\s*required\s*\)|\brequired\b/i.test(rawLabelText);
}
