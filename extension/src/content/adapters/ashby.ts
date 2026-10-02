import type { JobInfo } from "../../shared/types";
import { BaseAdapter } from "./base";
import { textOf } from "./generic";

export class AshbyAdapter extends BaseAdapter {
  id = "ASHBY" as const;

  detect(doc: Document, url: URL): boolean {
    return /(^|\.)ashbyhq\.com$/.test(url.hostname) || !!doc.querySelector(".ashby-application-form-container,[class*='ashby-application']");
  }

  jobInfo(doc: Document): Partial<JobInfo> {
    const out: Partial<JobInfo> = {};
    out.job_title = textOf(doc.querySelector("h1,.ashby-job-posting-heading"));
    out.job_id = /\/([0-9a-f]{8}-[0-9a-f-]{27})/i.exec(location.pathname)?.[1] ?? null;
    out.company = location.hostname.endsWith("ashbyhq.com") ? decodeURIComponent(location.pathname.split("/")[1] || "") || null : null;
    return out;
  }
}
