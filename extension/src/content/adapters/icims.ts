import type { JobInfo } from "../../shared/types";
import { BaseAdapter } from "./base";
import { textOf } from "./generic";

// Note: iCIMS usually renders applications inside an iframe. Scanning only reaches the frame this
// script runs in, so enable the extension on the iframe's own origin as well.
export class IcimsAdapter extends BaseAdapter {
  id = "ICIMS" as const;

  detect(doc: Document, url: URL): boolean {
    return /(^|\.)icims\.com$/.test(url.hostname) || !!doc.querySelector("[id^='iCIMS_'],[class*='iCIMS_']");
  }

  jobInfo(doc: Document): Partial<JobInfo> {
    const out: Partial<JobInfo> = {};
    out.job_title = textOf(doc.querySelector(".iCIMS_Header,h1,.iCIMS_JobTitle"));
    out.job_id = /\/jobs\/(\d+)/.exec(location.pathname)?.[1] ?? null;
    out.company = textOf(doc.querySelector(".iCIMS_Logo img[alt],.iCIMS_CompanyName")) ?? location.hostname.split(".")[0] ?? null;
    return out;
  }
}
