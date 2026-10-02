// Application history (doc §33, §41). Final statuses are always set by the user.
"use strict";
(() => {
  const { api, h, say } = Dash;
  const $ = (id) => document.getElementById(id);
  const STATUSES = [["STARTED", "Started"], ["IN_PROGRESS", "In progress"], ["READY_FOR_REVIEW", "Ready for review"], ["SUBMITTED", "Submitted"],
    ["INTERVIEW", "Interview"], ["REJECTED", "Rejected"], ["WITHDRAWN", "Withdrawn"], ["OFFER", "Offer"]];
  const LABEL = Object.fromEntries(STATUSES);

  function row(a) {
    const status = h("select", { "aria-label": `Status for ${a.company || "application"}` });
    for (const [v, t] of STATUSES) status.append(h("option", { value: v }, t));
    status.value = a.status;
    status.addEventListener("change", async () => {
      try { await api(`/applications/${a.id}`, { method: "PATCH", json: { status: status.value } }); say("h-msg", "Status updated.", "ok"); }
      catch (e) { say("h-msg", e.message, "err"); status.value = a.status; }
    });
    const details = h("div", { hidden: true });
    const toggle = h("button", { type: "button" }, "Details");
    let loaded = false;
    toggle.addEventListener("click", async () => {
      details.hidden = !details.hidden;
      if (details.hidden || loaded) return;
      try {
        const d = await api(`/applications/${a.id}`);
        loaded = true;
        const dl = h("dl", { class: "kv" });
        const add = (k, v) => { if (v) { dl.append(h("dt", {}, k), h("dd", {}, v)); } };
        add("Job ID", a.job_id); add("Location", a.location); add("ATS", a.ats);
        add("Resume", a.resume_filename ? `${a.resume_filename} (${(a.resume_sha256 || "").slice(0, 12)}…)` : null);
        add("Started", new Date(a.created_at).toLocaleString());
        add("Submitted", a.submitted_at ? new Date(a.submitted_at).toLocaleString() : null);
        details.append(dl);
        if (d.questions.length) {
          details.append(h("h3", { class: "sub" }, "Questions and answers"));
          const qa = h("dl", { class: "kv" });
          for (const q of d.questions) qa.append(h("dt", {}, q.label), h("dd", {}, q.answer || `(${q.status.toLowerCase().replace(/_/g, " ")})`));
          details.append(qa);
        }
      } catch (e) { say("h-msg", e.message, "err"); }
    });
    const del = h("button", { type: "button", class: "danger" }, "Delete");
    del.addEventListener("click", async () => {
      if (!confirm(`Delete the record for ${a.company || "this application"}? This only removes it from this computer.`)) return;
      try { await api(`/applications/${a.id}`, { method: "DELETE" }); await load(); } catch (e) { say("h-msg", e.message, "err"); }
    });
    const link = a.job_url && /^https?:\/\//.test(a.job_url) ? h("a", { href: a.job_url, target: "_blank", rel: "noopener noreferrer" }, "Open posting") : null;
    return h("li", {},
      h("div", { class: "title" }, [a.company, a.job_title].filter(Boolean).join(" · ") || "Untitled application"),
      h("div", { class: "meta" }, `${new Date(a.created_at).toLocaleDateString()} · ${a.ats}`),
      h("div", { class: "row" }, status, toggle, link, del), details);
  }

  async function load() {
    const fs = $("h-status");
    if (fs.options.length === 1) for (const [v, t] of STATUSES) fs.append(h("option", { value: v }, t));
    const qs = new URLSearchParams();
    if (fs.value) qs.set("status", fs.value);
    if ($("h-search").value.trim()) qs.set("q", $("h-search").value.trim());
    const items = await api("/applications" + (qs.toString() ? "?" + qs : ""));
    const list = $("h-list");
    list.replaceChildren();
    say("h-msg", items.length ? `${items.length} application${items.length === 1 ? "" : "s"}.` : "");
    if (!items.length) list.append(h("li", {}, "No applications yet. Start one from the extension on a job application page."));
    for (const a of items) list.append(row(a));
  }

  $("h-refresh").addEventListener("click", () => load().catch((e) => say("h-msg", e.message, "err")));
  $("h-status").addEventListener("change", () => load().catch((e) => say("h-msg", e.message, "err")));
  $("h-search").addEventListener("keydown", (e) => { if (e.key === "Enter") load().catch((err) => say("h-msg", err.message, "err")); });
  Dash.register("history", load);
})();
