// Repeatable sections (work experience, education, certifications, languages): decide which section a
// field belongs to and which entry (0, 1, ...) it is (doc §16-§19). Adapters can override with exact selectors.
import type { FieldDescriptor, SectionRef } from "../shared/types";
import { collapse, norm, ownText } from "./dom";

type Name = SectionRef["name"];

const SECTION_RES: Array<[Name, RegExp]> = [
  ["experience", /(work|professional|employment|job|career)\s*(experience|history)|^experience$|^employment$|^work history$/i],
  ["education", /^education\b|education\s*(history|and training|&)|academic|educational background/i],
  ["certification", /certif|licen[sc]e/i],
  ["language", /^languages?$|language skills|languages? (spoken|proficienc)|^languages? \(/i],
];
// Sub-headings inside a repeated entry ("Position 2", "Add another") must not end the section.
const KEEP = /^(position|job|employer|company|entry|school|degree|certificate|certification|language|work experience|education|employment)\s*#?\d*$|^(add|remove|delete|edit|save|cancel)\b/i;

export function classifyHeading(text: string): Name | "keep" | null {
  const t = collapse(text, 120).replace(/\s*\*\s*$/, "");
  if (!t) return "keep";
  for (const [name, re] of SECTION_RES) if (re.test(t)) return name;
  if (KEEP.test(t)) return "keep";
  return null;
}

const HEADING = "h1,h2,h3,h4,h5,h6,legend,[role='heading'],[class*='section-title' i],[class*='section-header' i],[data-section-title]";

export function isHeadingEl(el: Element): boolean {
  if (!el.matches(HEADING)) return false;
  if (el.tagName === "LEGEND") {
    const fs = el.closest("fieldset");
    if (fs) {
      const choice = fs.querySelectorAll("input[type=radio],input[type=checkbox]").length;
      const other = fs.querySelectorAll("input:not([type=radio]):not([type=checkbox]):not([type=hidden]),select,textarea").length;
      if (choice > 0 && other === 0) return false; // a question's legend, not a section heading
    }
  }
  return true;
}

export const HEADING_SELECTOR = HEADING;

export interface Entry { el: HTMLElement; d: FieldDescriptor }

const CONTROLS = "input,select,textarea,[role=combobox],button[aria-haspopup]";

/** The smallest ancestor of a heading that also holds form controls: the area the heading's section covers. */
function scopeOf(heading: Element): Element | null {
  for (let p = heading.parentElement; p && p !== p.ownerDocument.body; p = p.parentElement) {
    if (p.querySelector(CONTROLS)) return p;
  }
  return null; // flat page: the section lasts until the next heading
}

/**
 * ``order`` is every heading and every field in document order. Each field takes the section of the
 * nearest preceding heading; its index is how many fields with the same label the section already had.
 */
export function assignSections(
  order: Array<HTMLElement>,
  entries: Map<HTMLElement, FieldDescriptor>,
  override?: (el: HTMLElement) => SectionRef | null,
): void {
  let current: Name | null = null;
  let scope: Element | null = null;
  const seen = new Map<string, number>();
  for (const el of order) {
    const d = entries.get(el);
    if (!d) {
      if (isHeadingEl(el)) {
        const c = classifyHeading(ownText(el, 150));
        if (c !== "keep") {
          if (c !== current) seen.clear();
          current = c;
          scope = c ? scopeOf(el) : null;
        }
      }
      continue;
    }
    const forced = override?.(el);
    if (forced) { d.section = forced; continue; }
    // A field outside the block the heading introduced (a "Documents" area after "Education") is not part of it.
    if (current && scope && !scope.contains(el)) { current = null; scope = null; seen.clear(); }
    if (!current) continue;
    const sig = `${current}|${norm(d.label || d.aria_label || d.legend || d.placeholder || d.name || d.nearby_text || "")}`;
    const idx = seen.get(sig) ?? 0;
    seen.set(sig, idx + 1);
    d.section = { name: current, index: Math.min(idx, 50) };
  }
}
