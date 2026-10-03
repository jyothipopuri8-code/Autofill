import type { JobInfo } from "../../shared/types";
import { BaseAdapter } from "./base";
import { textOf } from "./generic";
import { collapse } from "../dom";

/** The value shown next to a label in the posting's overview card ("Location" -> "USA - Remote"). */
function overviewValue(doc: Document, label: string): string | null {
  for (const el of Array.from(doc.querySelectorAll<HTMLElement>("div,span,dt,th,h2,h3,h4,p"))) {
    if (el.children.length || el.closest("form")) continue;
    if (collapse(el.textContent, 40).toLowerCase() !== label) continue;
    const v = textOf(el.nextElementSibling as HTMLElement | null) ?? textOf(el.parentElement?.nextElementSibling as HTMLElement | null);
    if (v) return v;
  }
  return null;
}

export class AshbyAdapter extends BaseAdapter {
  id = "ASHBY" as const;

  detect(doc: Document, url: URL): boolean {
    return /(^|\.)ashbyhq\.com$/.test(url.hostname) || !!doc.querySelector(".ashby-application-form-container,[class*='ashby-application']");
  }

  jobInfo(doc: Document): Partial<JobInfo> {
    const out: Partial<JobInfo> = {};
    out.job_title = textOf(doc.querySelector("h1,.ashby-job-posting-heading"));
    out.job_id = /\/([0-9a-f]{8}-[0-9a-f-]{27})/i.exec(location.pathname)?.[1] ?? null;
    // Ashby titles pages "Role @ Company"; the URL slug ("deepgram") is only a lower-cased fallback.
    const t = /^(.+?)\s+@\s+(.+)$/.exec(collapse(doc.title, 300));
    if (t) { out.job_title = out.job_title || t[1]; out.company = t[2]; }
    else out.company = location.hostname.endsWith("ashbyhq.com") ? decodeURIComponent(location.pathname.split("/")[1] || "") || null : null;
    out.location = overviewValue(doc, "location");
    return out;
  }
}
