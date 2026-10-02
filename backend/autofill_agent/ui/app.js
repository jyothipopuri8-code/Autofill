// Local dashboard: resumes, profile, answers, history and settings. Talks only to this agent (same
// origin). Builds the DOM with createElement/textContent so stored text is never interpreted as HTML.
"use strict";

const API = "/api/v1";
const $ = (id) => document.getElementById(id);

let token = "";
try { token = sessionStorage.getItem("agentToken") || ""; } catch (e) { /* storage unavailable */ }
let reviewId = null;

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v; else if (v !== false && v != null) el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids) el.append(kid);
  return el;
}

// Tabs register a loader here; the dashboard calls it when the tab opens.
const Dash = { tabs: {}, register(name, load) { this.tabs[name] = load; }, api: null, h: null, say: null, errorText: null };

function say(id, text, kind) {
  const el = $(id);
  el.textContent = text || "";
  el.className = "msg" + (kind ? " " + kind : "");
}

function errorText(body, status) {
  const d = body && body.detail;
  if (Array.isArray(d)) return d.map((e) => `${(e.loc || []).filter((x) => x !== "body").join(" > ")}: ${e.msg}`).join("; ");
  return typeof d === "string" ? d : `Request failed (${status})`;
}

async function api(path, opts = {}) {
  const headers = { Authorization: "Bearer " + token, ...(opts.headers || {}) };
  if (opts.json !== undefined) { headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(opts.json); }
  const res = await fetch(API + path, { method: opts.method || "GET", headers, body: opts.body });
  if (res.status === 401) { showAuth("Token not accepted."); throw new Error("Not authorized"); }
  if (res.status === 204) return null;
  let body = null;
  try { body = await res.json(); } catch (e) { /* no body */ }
  if (!res.ok) throw new Error(errorText(body, res.status));
  return body;
}

// --- Connection ---------------------------------------------------------------

function showTab(name) {
  if (!Dash.tabs[name]) name = "resumes";
  for (const p of document.querySelectorAll("[data-panel]")) p.hidden = p.id !== name;
  if (name !== "resumes") $("review").hidden = true;
  for (const b of document.querySelectorAll("#tabs button")) b.setAttribute("aria-current", b.dataset.tab === name ? "page" : "false");
  try { sessionStorage.setItem("agentTab", name); } catch (e) { /* ignore */ }
  Promise.resolve(Dash.tabs[name]()).catch((e) => { if (e.message !== "Not authorized") console.error(e); });
}

function showAuth(msg) {
  token = "";
  try { sessionStorage.removeItem("agentToken"); } catch (e) { /* ignore */ }
  $("auth").hidden = false; $("tabs").hidden = true;
  for (const p of document.querySelectorAll("[data-panel]")) p.hidden = true;
  $("review").hidden = true;
  $("conn").textContent = "Not connected"; $("conn").className = "badge";
  say("auth-msg", msg, "err");
}

async function connect() {
  token = $("token").value.trim() || token;
  if (!token) return say("auth-msg", "Enter the token first.", "err");
  try {
    await api("/status");
    try { sessionStorage.setItem("agentToken", token); } catch (e) { /* ignore */ }
    $("token").value = "";
    $("auth").hidden = true; $("tabs").hidden = false;
    $("conn").textContent = "Connected"; $("conn").className = "badge ok";
    let tab = "";
    try { tab = sessionStorage.getItem("agentTab") || ""; } catch (e) { /* ignore */ }
    showTab(tab || "resumes");
  } catch (e) {
    if (e.message !== "Not authorized") showAuth("Cannot reach the agent: " + e.message);
  }
}

// --- Resume list --------------------------------------------------------------

const STATUS_LABEL = { UPLOADED: "Not parsed", PARSED: "Needs review", VERIFIED: "Verified" };

async function loadResumes() {
  const list = $("resume-list");
  list.replaceChildren();
  const items = await api("/resumes?include_archived=true");
  if (!items.length) list.append(h("li", {}, "No resumes yet. Upload a PDF or DOCX above."));
  for (const r of items) list.append(resumeCard(r));
}

function resumeCard(r) {
  const act = (label, fn, cls) => {
    const b = h("button", { class: cls || "", type: "button" }, label);
    b.addEventListener("click", async () => {
      b.disabled = true;
      try { await fn(); } catch (e) { say("resume-msg", e.message, "err"); }
      b.disabled = false;
    });
    return b;
  };
  const reload = async () => { await loadResumes(); };
  const badges = h("div", { class: "row" },
    h("span", { class: "badge " + (r.status === "VERIFIED" ? "ok" : "warn") }, STATUS_LABEL[r.status] || r.status));
  if (r.is_current) badges.append(h("span", { class: "badge ok" }, "Current"));
  if (r.archived_at) badges.append(h("span", { class: "badge" }, "Archived"));

  const buttons = h("div", { class: "row" });
  buttons.append(act(r.parsed_at ? "Re-parse" : "Parse", async () => {
    await api(`/resumes/${r.id}/parse`, { method: "POST" });
    say("resume-msg", "Parsed. Review it before using it.", "ok");
    await reload(); await openReview(r.id);
  }));
  buttons.append(act("Review", () => openReview(r.id)));
  if (!r.archived_at) {
    buttons.append(act("Set current", async () => { await api(`/resumes/${r.id}/set-current`, { method: "POST" }); await reload(); }));
    buttons.append(act("Archive", async () => { await api(`/resumes/${r.id}/archive`, { method: "POST" }); await reload(); }));
  } else {
    buttons.append(act("Unarchive", async () => { await api(`/resumes/${r.id}/unarchive`, { method: "POST" }); await reload(); }));
  }
  buttons.append(act("Delete", async () => {
    if (!confirm(`Delete "${r.filename}" and its stored file? Application history keeps its record.`)) return;
    await api(`/resumes/${r.id}`, { method: "DELETE" });
    if (reviewId === r.id) closeReview();
    await reload();
  }, "danger"));

  return h("li", {},
    h("div", { class: "title" }, r.filename),
    h("div", { class: "meta" }, `SHA-256 ${r.sha256.slice(0, 12)}…  ·  ${(r.size_bytes / 1024).toFixed(0)} KB  ·  uploaded ${new Date(r.uploaded_at).toLocaleString()}`),
    badges, buttons);
}

async function upload() {
  const file = $("file").files[0];
  if (!file) return say("resume-msg", "Choose a PDF or DOCX file first.", "err");
  const body = new FormData();
  body.append("file", file);
  try {
    await api("/resumes", { method: "POST", body });
    $("file").value = "";
    say("resume-msg", "Uploaded. Click Parse to extract its information.", "ok");
    await loadResumes();
  } catch (e) { say("resume-msg", e.message, "err"); }
}

// --- Review form --------------------------------------------------------------

const CONTACT = [
  ["full_name", "Full name"], ["first_name", "First name"], ["last_name", "Last name"], ["email", "Email"],
  ["phone", "Phone"], ["location", "Location"], ["linkedin_url", "LinkedIn URL"], ["github_url", "GitHub URL"], ["website_url", "Website URL"],
];
const LISTS = {
  experience: { label: "Work experience", add: "Add position", fields: [
    ["title", "Job title"], ["company", "Company"], ["location", "Location"], ["start_date", "Start (YYYY-MM)"],
    ["end_date", "End (YYYY-MM)"], ["current", "I currently work here", "bool"], ["description", "Description", "area"]] },
  education: { label: "Education", add: "Add school", fields: [
    ["school", "School"], ["degree", "Degree"], ["field_of_study", "Field of study"], ["start_date", "Start (YYYY-MM)"],
    ["graduation_date", "Graduation (YYYY-MM)"], ["expected_graduation_date", "Expected graduation (YYYY-MM)"]] },
  certifications: { label: "Certifications", add: "Add certification", fields: [
    ["name", "Name"], ["number", "Certification number (only if shown on the resume)"], ["issued_date", "Issued (YYYY-MM)"], ["expiration_date", "Expires (YYYY-MM)"]] },
  languages: { label: "Languages", add: "Add language", fields: [
    ["language", "Language"], ["proficiency", "Proficiency (leave empty if unknown)"]] },
};

function fieldEl(name, label, kind, value) {
  const input = kind === "area" ? h("textarea", { "data-f": name }) : h("input", { "data-f": name, type: kind === "bool" ? "checkbox" : "text" });
  if (kind === "bool") input.checked = !!value; else input.value = value == null ? "" : String(value);
  return h("label", { class: kind === "bool" ? "check" : "" }, kind === "bool" ? input : label, kind === "bool" ? label : input);
}

function entryEl(spec, data) {
  const grid = h("div", { class: "grid" });
  for (const [name, label, kind] of spec.fields) grid.append(fieldEl(name, label, kind, data && data[name]));
  const remove = h("button", { type: "button", class: "danger" }, "Remove");
  const entry = h("div", { class: "entry" }, grid, remove);
  remove.addEventListener("click", () => entry.remove());
  return entry;
}

function buildForm(data) {
  const form = $("form");
  form.replaceChildren();

  const contact = h("fieldset", { "data-section": "contact" }, h("legend", {}, "Contact"));
  const grid = h("div", { class: "grid" });
  for (const [name, label] of CONTACT) grid.append(fieldEl(name, label, "text", (data.contact || {})[name]));
  contact.append(grid);
  form.append(contact);

  const summary = h("fieldset", {}, h("legend", {}, "Summary"), h("textarea", { id: "f-summary" }));
  summary.querySelector("textarea").value = data.summary || "";
  form.append(summary);

  const skills = h("fieldset", {}, h("legend", {}, "Skills (one per line or comma-separated)"), h("textarea", { id: "f-skills" }));
  skills.querySelector("textarea").value = (data.skills || []).join("\n");
  form.append(skills);

  for (const [key, spec] of Object.entries(LISTS)) {
    const box = h("div", {});
    const fs = h("fieldset", { "data-list": key }, h("legend", {}, spec.label), box);
    for (const item of data[key] || []) box.append(entryEl(spec, item));
    const add = h("button", { type: "button" }, spec.add);
    add.addEventListener("click", () => box.append(entryEl(spec, {})));
    fs.append(add);
    form.append(fs);
  }
}

function readEntry(entry) {
  const out = {};
  for (const el of entry.querySelectorAll("[data-f]")) {
    out[el.dataset.f] = el.type === "checkbox" ? el.checked : el.value.trim();
  }
  return out;
}

function collect() {
  const contact = {};
  for (const el of document.querySelectorAll('[data-section="contact"] [data-f]')) contact[el.dataset.f] = el.value.trim();
  const data = {
    contact,
    summary: $("f-summary").value.trim(),
    skills: $("f-skills").value.split(/[\n,;]/).map((s) => s.trim()).filter(Boolean),
  };
  for (const key of Object.keys(LISTS)) {
    data[key] = [...document.querySelectorAll(`[data-list="${key}"] .entry`)].map(readEntry)
      .filter((e) => Object.values(e).some((v) => v && v !== true));
  }
  return data;
}

async function openReview(id) {
  const res = await api(`/resumes/${id}/data`);
  const data = res.effective_data;
  if (!data) { say("resume-msg", "Parse this resume first, or it has no data to review.", "err"); return; }
  reviewId = id;
  $("review").hidden = false;
  $("review-title").textContent = res.verified ? "Review (verified)" : "Review parsed resume";
  const w = $("warnings");
  w.replaceChildren();
  for (const msg of (res.parsed_data && res.parsed_data.warnings) || []) w.append(h("li", {}, msg));
  buildForm(data);
  say("review-msg", "");
  $("review").scrollIntoView({ behavior: "smooth" });
}

function closeReview() { reviewId = null; $("review").hidden = true; }

async function saveCorrections() {
  return api(`/resumes/${reviewId}/verified-data`, { method: "PUT", json: collect() });
}

// --- Wiring -------------------------------------------------------------------

$("connect").addEventListener("click", connect);
$("token").addEventListener("keydown", (e) => { if (e.key === "Enter") connect(); });
$("upload").addEventListener("click", upload);
$("close").addEventListener("click", closeReview);
$("save").addEventListener("click", async () => {
  try { await saveCorrections(); say("review-msg", "Corrections saved. Not verified yet.", "ok"); await loadResumes(); }
  catch (e) { say("review-msg", e.message, "err"); }
});
$("verify").addEventListener("click", async () => {
  try {
    await saveCorrections();
    await api(`/resumes/${reviewId}/verify`, { method: "POST" });
    say("review-msg", "Verified. This resume's data can now be used for filling.", "ok");
    await loadResumes();
  } catch (e) { say("review-msg", e.message, "err"); }
});

Dash.api = api; Dash.h = h; Dash.say = say; Dash.errorText = errorText;
Dash.register("resumes", loadResumes);
for (const b of document.querySelectorAll("#tabs button")) b.addEventListener("click", () => showTab(b.dataset.tab));
window.addEventListener("DOMContentLoaded", () => { if (token) connect(); });
