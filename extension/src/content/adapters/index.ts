import type { AtsId } from "../../shared/types";
import { Adapter } from "./base";
import { AshbyAdapter } from "./ashby";
import { GenericAdapter } from "./generic";
import { GreenhouseAdapter } from "./greenhouse";
import { IcimsAdapter } from "./icims";
import { LeverAdapter } from "./lever";
import { SmartRecruitersAdapter } from "./smartrecruiters";
import { WorkdayAdapter } from "./workday";

const REGISTRY: Adapter[] = [
  new GreenhouseAdapter(), new LeverAdapter(), new WorkdayAdapter(), new AshbyAdapter(), new IcimsAdapter(), new SmartRecruitersAdapter(),
];
const GENERIC = new GenericAdapter();

/** The first adapter whose signature matches this page; the generic adapter otherwise. */
export function detectAdapter(doc: Document, url: URL): Adapter {
  return REGISTRY.find((a) => { try { return a.detect(doc, url); } catch { return false; } }) ?? GENERIC;
}

export function adapterById(id: AtsId): Adapter {
  return REGISTRY.find((a) => a.id === id) ?? GENERIC;
}

export type { Adapter };
