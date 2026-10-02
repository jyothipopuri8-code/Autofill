import type { JobInfo } from "../../shared/types";
import { collapse, isVisible } from "../dom";
import { BaseAdapter, metaContent } from "./base";
import { textOf } from "./generic";

export class GreenhouseAdapter extends BaseAdapter {
  id = "GREENHOUSE" as const;

  detect(doc: Document, url: URL): boolean {
    return /(^|\.)greenhouse\.io$/.test(url.hostname)
      || !!doc.querySelector("#grnhse_app,#application_form,[data-greenhouse]")
      || (url.searchParams.has("gh_jid") && !!doc.querySelector("#main_fields,#application_form"));
  }

  jobInfo(doc: Document): Partial<JobInfo> {
    const out: Partial<JobInfo> = {};
    const m = /^Job Application for (.+?) at (.+)$/i.exec(doc.title.trim());
    if (m) { out.job_title = collapse(m[1], 200); out.company = collapse(m[2], 200); }
    out.job_title ??= textOf(doc.querySelector(".app-title,.job__title h1,h1.section-header,#header .title,h1"));
    out.company ??= textOf(doc.querySelector(".company-name,.logo img[alt]")) ?? metaContent(doc, "meta[property='og:site_name']");
    out.location = textOf(doc.querySelector(".location,.job__location,.job-post-location"));
    const id = /\/jobs\/(\d+)/.exec(location.pathname)?.[1] ?? new URL(location.href).searchParams.get("gh_jid");
    if (id) out.job_id = id;
    out.job_description = textOf(doc.querySelector("#content .job__description,.job__description,#content,.job-post"), 20000);
    return out;
  }

  navButtons(doc: Document) {
    const nav = super.navButtons(doc);
    for (const b of Array.from(doc.querySelectorAll<HTMLElement>("button[type=submit],input[type=submit]")).filter(isVisible)) {
      if (!nav.submit.includes(b)) nav.submit.push(b);
    }
    return nav;
  }
}
