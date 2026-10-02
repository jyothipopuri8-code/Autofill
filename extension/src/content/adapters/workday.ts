import type { FieldDescriptor, JobInfo, SectionRef } from "../../shared/types";
import { isVisible, sleep, waitFor } from "../dom";
import { BaseAdapter } from "./base";
import { textOf } from "./generic";

const SECTION_PREFIXES: Array<[RegExp, SectionRef["name"]]> = [
  [/^workExperience-(\d+)/i, "experience"],
  [/^education-(\d+)/i, "education"],
  [/^certification-(\d+)/i, "certification"],
  [/^language-(\d+)/i, "language"],
];

// Based on Workday's public data-automation-id conventions. Not yet validated against live tenants.
export class WorkdayAdapter extends BaseAdapter {
  id = "WORKDAY" as const;

  detect(doc: Document, url: URL): boolean {
    return /(^|\.)myworkdayjobs\.com$|(^|\.)workday\.com$/.test(url.hostname) || !!doc.querySelector("[data-automation-id='jobPostingHeader'],[data-automation-id='legalNameSection_firstName']");
  }

  jobInfo(doc: Document): Partial<JobInfo> {
    const out: Partial<JobInfo> = {};
    out.job_title = textOf(doc.querySelector("[data-automation-id='jobPostingHeader'],h2[data-automation-id='jobPostingHeader'],h1"));
    out.company = location.hostname.split(".")[0] || null;
    out.job_id = /_((?:R|JR)-?\d+)/i.exec(location.pathname)?.[1] ?? textOf(doc.querySelector("[data-automation-id='requisitionId']"));
    out.location = textOf(doc.querySelector("[data-automation-id='locations'] dd,[data-automation-id='locations']"));
    out.job_description = textOf(doc.querySelector("[data-automation-id='jobPostingDescription']"), 20000);
    return out;
  }

  extraControls(doc: Document): HTMLElement[] {
    return Array.from(doc.querySelectorAll<HTMLElement>(
      "button[aria-haspopup='listbox'],[data-automation-id$='dropdown'] button,[data-automation-id='multiSelectContainer']"));
  }

  decorate(el: HTMLElement, d: FieldDescriptor): void {
    const auto = el.getAttribute("data-automation-id") || el.closest("[data-automation-id]")?.getAttribute("data-automation-id");
    if (auto && !d.name) d.name = auto;
    if (auto) d.id = d.id && !/^input-/.test(d.id) ? d.id : auto;
  }

  sectionOf(el: HTMLElement): SectionRef | null {
    const holder = el.closest("[data-automation-id]");
    for (let node: Element | null = holder; node; node = node.parentElement?.closest("[data-automation-id]") ?? null) {
      const auto = node.getAttribute("data-automation-id") || "";
      for (const [re, name] of SECTION_PREFIXES) {
        const m = re.exec(auto);
        if (m) return { name, index: Math.max(0, parseInt(m[1], 10) - 1) };
      }
    }
    return null;
  }

  async addAnother(doc: Document, section: SectionRef["name"]): Promise<boolean> {
    const group = doc.querySelector<HTMLElement>({
      experience: "[data-automation-id='workExperienceSection']", education: "[data-automation-id='educationSection']",
      certification: "[data-automation-id='certificationSection']", language: "[data-automation-id='languageSection']",
    }[section]);
    const btn = group?.querySelector<HTMLElement>("button[data-automation-id='add-button'],button[data-automation-id='Add']");
    if (!btn || !isVisible(btn)) return super.addAnother(doc, section);
    const before = doc.querySelectorAll("input,select,textarea,button[aria-haspopup]").length;
    btn.click();
    const grew = await waitFor(() => doc.querySelectorAll("input,select,textarea,button[aria-haspopup]").length > before, 3000);
    await sleep(150);
    return !!grew;
  }
}
