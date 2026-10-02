import type { JobInfo } from "../../shared/types";
import { BaseAdapter } from "./base";
import { textOf } from "./generic";

// SmartRecruiters renders form controls as web components (spl-*) with open shadow roots; the scanner
// pierces open shadow roots, so no special selectors are needed here.
export class SmartRecruitersAdapter extends BaseAdapter {
  id = "SMARTRECRUITERS" as const;

  detect(doc: Document, url: URL): boolean {
    return /(^|\.)smartrecruiters\.com$/.test(url.hostname) || !!doc.querySelector("oc-oneclick-form,[class*='smartrecruiters' i],spl-input");
  }

  jobInfo(doc: Document): Partial<JobInfo> {
    const out: Partial<JobInfo> = {};
    out.job_title = textOf(doc.querySelector("h1.job-title,h1"));
    out.company = location.pathname.split("/")[1] || null;
    out.job_id = /\/(\d{6,})/.exec(location.pathname)?.[1] ?? null;
    return out;
  }
}
