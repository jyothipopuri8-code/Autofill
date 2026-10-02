// Job details for the session: what the page says about the role (doc §4, §11). Adapters know their
// own markup; everything else falls back to page metadata.
import type { JobInfo } from "../shared/types";
import type { Adapter } from "./adapters/base";
import { collapse, isVisible } from "./dom";

const TRACKING = /^(utm_|fbclid|gclid|mc_|ref$|referrer|src$|source$|trk)/i;
const JOB_ID_PARAMS = ["gh_jid", "jobid", "job_id", "jid", "requisitionid", "req_id", "reqid", "jr_id", "requisition"];

export function cleanUrl(href: string): string {
  const u = new URL(href);
  u.hash = "";
  for (const k of Array.from(u.searchParams.keys())) if (TRACKING.test(k)) u.searchParams.delete(k);
  return u.toString();
}

function meta(doc: Document, sel: string): string | null {
  return doc.querySelector<HTMLMetaElement>(sel)?.content?.trim() || null;
}

function companyFromHost(host: string): string | null {
  const parts = host.replace(/^www\./, "").split(".");
  const generic = new Set(["jobs", "careers", "apply", "boards", "job-boards", "hire", "recruiting", "greenhouse", "lever", "myworkdayjobs", "ashbyhq", "icims", "smartrecruiters"]);
  const sub = parts.length > 2 ? parts[0] : parts[0];
  const pick = generic.has(parts[0]) && parts.length > 2 ? parts[1] : sub;
  return generic.has(pick) ? null : pick.replace(/[-_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function description(doc: Document): string | null {
  const el = doc.querySelector<HTMLElement>("[class*='job-description' i],[id*='job-description' i],[class*='jobdescription' i],[id*='jobDescription' i],[class*='posting' i] [class*='content' i],main,[role=main]");
  if (!el) return null;
  // Take the visible text only, and never the form's own controls.
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll("form,input,select,textarea,script,style,nav,header,footer,button").forEach((n) => n.remove());
  const t = collapse(clone.textContent, 20000);
  return t.length >= 80 ? t : null;
}

export function collectJob(doc: Document, adapter: Adapter, url: URL): JobInfo {
  const a = adapter.jobInfo(doc);
  const h1 = Array.from(doc.querySelectorAll<HTMLElement>("h1")).find(isVisible)?.textContent;
  let job_id = a.job_id ?? null;
  if (!job_id) {
    for (const [k, v] of url.searchParams) if (JOB_ID_PARAMS.includes(k.toLowerCase()) && v) { job_id = v.slice(0, 100); break; }
  }
  const og = meta(doc, "meta[property='og:title']");
  return {
    company: collapse(a.company ?? meta(doc, "meta[property='og:site_name']") ?? meta(doc, "meta[name='application-name']") ?? companyFromHost(url.hostname), 200) || null,
    job_title: collapse(a.job_title ?? h1 ?? og ?? doc.title, 200) || null,
    job_id: job_id ? collapse(job_id, 100) : null,
    url: cleanUrl(url.href),
    location: a.location ? collapse(a.location, 200) : null,
    job_description: a.job_description ?? description(doc),
    ats: adapter.id,
  };
}
