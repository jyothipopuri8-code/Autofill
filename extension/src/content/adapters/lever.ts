import type { JobInfo } from "../../shared/types";
import { collapse } from "../dom";
import { BaseAdapter } from "./base";
import { textOf } from "./generic";

export class LeverAdapter extends BaseAdapter {
  id = "LEVER" as const;

  detect(doc: Document, url: URL): boolean {
    return /(^|\.)lever\.co$/.test(url.hostname) || !!doc.querySelector(".application-page,form[action*='lever.co'],.posting-page");
  }

  jobInfo(doc: Document): Partial<JobInfo> {
    const out: Partial<JobInfo> = {};
    out.job_title = textOf(doc.querySelector(".posting-headline h2,.posting-header h2,h2"));
    const m = /^(.+?)\s+-\s+(.+)$/.exec(doc.title.trim());
    if (m) { out.company = collapse(m[1], 200); out.job_title ??= collapse(m[2], 200); }
    out.company ??= doc.querySelector<HTMLImageElement>(".main-header-logo img,.logo img")?.alt?.trim() || null;
    out.location = textOf(doc.querySelector(".posting-categories .location,.location"));
    out.job_id = /\/([0-9a-f]{8}-[0-9a-f-]{27})/i.exec(location.pathname)?.[1] ?? null;
    out.job_description = textOf(doc.querySelector(".posting-page .content,.section-wrapper.page-full-width,[data-qa='job-description']"), 20000);
    return out;
  }
}
