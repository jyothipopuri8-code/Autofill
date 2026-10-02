import type { JobInfo } from "../../shared/types";
import { collapse } from "../dom";
import { BaseAdapter } from "./base";

/** Generic company career pages: no ATS-specific knowledge. */
export class GenericAdapter extends BaseAdapter {
  id = "GENERIC" as const;
  jobInfo(): Partial<JobInfo> { return {}; }
}

export function textOf(el: Element | null, max = 200): string | null {
  const t = collapse(el?.textContent, max);
  return t || null;
}
