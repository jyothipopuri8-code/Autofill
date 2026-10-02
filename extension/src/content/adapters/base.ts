// Shared ATS adapter behaviour. Specific adapters override only what differs (doc §30).
import type { AtsId, FieldDescriptor, JobInfo, SectionRef } from "../../shared/types";
import { collapse, isVisible, norm, ownText, sleep, waitFor } from "../dom";
import { classifyHeading, HEADING_SELECTOR } from "../sections";

export interface NavButtons { next: HTMLElement[]; submit: HTMLElement[] }

export interface Adapter {
  id: AtsId;
  detect(doc: Document, url: URL): boolean;
  jobInfo(doc: Document): Partial<JobInfo>;
  /** Extra controls the generic selector would miss (custom dropdown buttons and so on). */
  extraControls(doc: Document): HTMLElement[];
  /** Adjust a descriptor with ATS-specific knowledge (stable names, labels). */
  decorate(el: HTMLElement, d: FieldDescriptor): void;
  /** Exact section for a field, or null to use generic heading-based detection. */
  sectionOf(el: HTMLElement): SectionRef | null;
  addAnother(doc: Document, section: SectionRef["name"]): Promise<boolean>;
  navButtons(doc: Document): NavButtons;
}

const NEXT_RE = /^(next|continue|save (and|&) continue|save (and|&) next|proceed|next step|continue to .+|review( (and|&) submit)?|go to next step)$/i;
const SUBMIT_RE = /(^|\b)(submit( (my )?application)?|send application|finish( application)?|complete application|confirm( (and|&) submit)?)(\b|$)/i;
const ADD_RE = /^(\+\s*)?(add|add another|add more|\+ add)( another| more)?( (position|job|employment|experience|work experience|school|education|degree|certification|certificate|language))?$/i;

export function textOfButton(b: HTMLElement): string {
  return collapse((b as HTMLInputElement).value && b.tagName === "INPUT" ? (b as HTMLInputElement).value : b.textContent || b.getAttribute("aria-label"), 80);
}

export class BaseAdapter implements Adapter {
  id: AtsId = "GENERIC";
  detect(_doc: Document, _url: URL): boolean { return true; }
  jobInfo(_doc: Document): Partial<JobInfo> { return {}; }
  extraControls(_doc: Document): HTMLElement[] { return []; }
  decorate(_el: HTMLElement, _d: FieldDescriptor): void {}
  sectionOf(_el: HTMLElement): SectionRef | null { return null; }

  navButtons(doc: Document): NavButtons {
    const out: NavButtons = { next: [], submit: [] };
    const fieldCount = doc.querySelectorAll("input:not([type=hidden]),select,textarea").length;
    for (const b of Array.from(doc.querySelectorAll<HTMLElement>("button,input[type=submit],input[type=button],a[role=button],[role=button]"))) {
      if (!isVisible(b)) continue;
      const t = textOfButton(b);
      if (!t || t.length > 40) continue;
      if (SUBMIT_RE.test(t) || (/^apply( now)?$/i.test(t) && fieldCount >= 3 && b.closest("form")) || (b.getAttribute("type") === "submit" && /submit|send|apply/i.test(t))) out.submit.push(b);
      else if (NEXT_RE.test(t)) out.next.push(b);
    }
    return out;
  }

  /** Click the "Add another" button for a section and wait for new fields to appear. */
  async addAnother(doc: Document, section: SectionRef["name"]): Promise<boolean> {
    const buttons = Array.from(doc.querySelectorAll<HTMLElement>("button,a[role=button],[role=button],a")).filter((b) => isVisible(b) && ADD_RE.test(textOfButton(b)));
    const btn = buttons.find((b) => this.sectionOfButton(b) === section) ?? (buttons.length === 1 ? buttons[0] : undefined);
    if (!btn) return false;
    const before = doc.querySelectorAll("input,select,textarea").length;
    btn.click();
    const grew = await waitFor(() => doc.querySelectorAll("input,select,textarea").length > before, 2500);
    await sleep(80);
    return !!grew;
  }

  protected sectionOfButton(b: HTMLElement): SectionRef["name"] | null {
    const t = norm(textOfButton(b));
    for (const [word, name] of [["experience", "experience"], ["position", "experience"], ["job", "experience"], ["employment", "experience"], ["school", "education"], ["education", "education"], ["degree", "education"], ["certif", "certification"], ["language", "language"]] as const) {
      if (t.includes(word)) return name;
    }
    // Otherwise the nearest preceding heading decides.
    let node: Element | null = b;
    for (let i = 0; node && i < 6; i++, node = node.parentElement) {
      let prev: Element | null = node.previousElementSibling;
      for (let h = 0; prev && h < 12; h++, prev = prev.previousElementSibling) {
        const head = prev.matches(HEADING_SELECTOR) ? prev : prev.querySelector(HEADING_SELECTOR);
        if (head) {
          const c = classifyHeading(ownText(head));
          if (c && c !== "keep") return c;
        }
      }
    }
    return null;
  }
}

export function metaContent(doc: Document, sel: string): string | null {
  return doc.querySelector<HTMLMetaElement>(sel)?.content?.trim() || null;
}
