// Types shared by the content script, background worker and popup. They mirror the
// agent's API (backend/autofill_agent/engine/descriptor.py and resolver.py).

export type Kind =
  | "text" | "email" | "tel" | "number" | "url" | "textarea" | "select" | "custom_select"
  | "radio_group" | "checkbox" | "checkbox_group" | "date" | "month_year" | "autocomplete"
  | "file" | "password" | "captcha" | "unknown";

export type Ownership = "EMPTY" | "SITE_DEFAULT" | "AGENT_FILLED" | "USER_FILLED" | "USER_MODIFIED_AGENT_VALUE";

export interface Option { value: string; label: string }
export interface SectionRef { name: "experience" | "education" | "certification" | "language"; index: number }

export interface FieldDescriptor {
  key: string;
  kind: Kind;
  label: string | null;
  name: string | null;
  id: string | null;
  placeholder: string | null;
  aria_label: string | null;
  autocomplete: string | null;
  input_type: string | null;
  nearby_text: string | null;
  legend: string | null;
  options: Option[];
  required: boolean;
  current_value: string | null;
  ownership: Ownership;
  section: SectionRef | null;
  date_format: string | null;
  maxlength: number | null;
  visible: boolean;
  disabled: boolean;
}

export type Action = "fill" | "review" | "confirm" | "ask" | "skip" | "keep" | "user_action" | "attach" | "conflict";
export type FieldStatus =
  | "PENDING" | "FILLED" | "MISSING_REQUIRED" | "NEEDS_REVIEW" | "USER_ACTION_REQUIRED"
  | "FAILED_TO_FILL" | "SKIPPED" | "OPTIONAL_EMPTY";

export interface FieldResult {
  key: string;
  canonical_field: string | null;
  label: string | null;
  kind: Kind;
  section: string | null;
  section_index: number | null;
  required: boolean;
  value: string | null;
  checked: boolean | null;
  option: Option | null;
  parts: { year: number | null; month: number | null; day: number | null } | null;
  source: string;
  confidence: number;
  band: "READY" | "REVIEW" | "DO_NOT_FILL";
  action: Action;
  status: FieldStatus;
  reason: string | null;
  sensitive: boolean;
  conflict: { canonical_field: string; profile_value: string; resume_value: string } | null;
  suggestion: string | null;
  match_score: number;
  signals: string[];
  auto?: boolean;
}

export interface AttentionItem {
  page_index: number; key: string; label: string | null; canonical_field: string | null; action: Action;
  status: FieldStatus; reason: string | null; required: boolean; sensitive: boolean; suggestion: string | null;
  conflict: FieldResult["conflict"]; kind: Kind | null;
}

export interface ResumeBrief { id: number; filename: string; sha256: string; verified: boolean }
export interface ResumeState { expected: ResumeBrief | null; current: ResumeBrief | null; blocked: string | null; warning: string | null }

export interface Counts {
  detected: number; complete: number; missing_required: number; needs_review: number; user_action_required: number;
  failed_to_fill: number; skipped: number; optional_empty: number; pending: number;
}

export interface AnalyzeResponse {
  session_id: number; page_index: number; mode: Mode; results: FieldResult[]; counts: Counts;
  needs_attention: AttentionItem[]; resume: ResumeState; section_counts: Record<string, number>;
}

export type Mode = "SAFE" | "STANDARD" | "MANUAL_ASSIST";
export type AtsId = "GENERIC" | "GREENHOUSE" | "LEVER" | "WORKDAY" | "ASHBY" | "ICIMS" | "SMARTRECRUITERS";

export interface JobInfo {
  company: string | null; job_title: string | null; job_id: string | null; url: string;
  location: string | null; job_description: string | null; ats: AtsId;
}

export interface SessionSummary {
  id: number; application_id: number; status: string; current_page_url: string | null; current_page_index: number;
  application: { company: string | null; job_title: string | null; ats: string; status: string; resume_filename: string | null };
  counts: Counts; resume?: ResumeState;
}

// --- messaging ---------------------------------------------------------------

export interface ApiRequest { type: "api"; method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE"; path: string; body?: unknown; binary?: boolean }
export interface ApiResponse { ok: boolean; status: number; data: any; headers?: Record<string, string>; base64?: string; error?: string }

export type PopupToContent = { type: "start" } | { type: "ping" } | { type: "toggle" };
export type TabState = { sessionId: number; origin: string; pageIndex: number } | null;
