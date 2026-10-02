// Reusable answer library and remembered (approved) answers.
"use strict";
(() => {
  const { api, h, say } = Dash;
  const $ = (id) => document.getElementById(id);
  const POLICY = { ASK_ME: "Ask me each time", AUTOFILL: "Fill automatically", NEVER_FILL: "Never fill" };

  function fillForm(a) {
    $("a-key").value = a ? a.key : "";
    $("a-category").value = a ? a.category : "";
    $("a-policy").value = a ? a.policy : "ASK_ME";
    $("a-verified").value = a ? a.verification : "UNVERIFIED";
    $("a-value").value = a && a.value ? a.value : "";
    $("a-notes").value = a && a.notes ? a.notes : "";
    say("a-msg", "");
  }

  async function loadLibrary() {
    const [items, keys] = await Promise.all([api("/answers"), api("/answers/standard-keys")]);
    const dl = $("a-keys");
    dl.replaceChildren(...Object.keys(keys).map((k) => h("option", { value: k })));
    const list = $("library-list");
    list.replaceChildren();
    if (!items.length) list.append(h("li", {}, "No answers yet. Add one below."));
    for (const a of items) {
      const edit = h("button", { type: "button" }, "Edit");
      edit.addEventListener("click", () => { fillForm(a); $("library-form").scrollIntoView({ behavior: "smooth" }); });
      const del = h("button", { type: "button", class: "danger" }, "Delete");
      del.addEventListener("click", async () => {
        if (!confirm(`Delete the answer "${a.key}"?`)) return;
        try { await api(`/answers/${encodeURIComponent(a.key)}`, { method: "DELETE" }); await loadLibrary(); }
        catch (e) { say("a-msg", e.message, "err"); }
      });
      list.append(h("li", {},
        h("div", { class: "title" }, a.key),
        h("div", { class: "meta" }, `${a.category} · ${POLICY[a.policy]} · ${a.verification === "VERIFIED" ? "verified" : "not verified"}`),
        h("div", {}, a.value || "(no value)"), h("div", { class: "row" }, edit, del)));
    }
  }

  async function saveAnswer() {
    const key = $("a-key").value.trim();
    if (!key) return say("a-msg", "Enter a key such as desired_salary.", "err");
    try {
      await api(`/answers/${encodeURIComponent(key)}`, { method: "PUT", json: {
        category: $("a-category").value.trim() || "general", policy: $("a-policy").value, verification: $("a-verified").value,
        value: $("a-value").value.trim() || null, notes: $("a-notes").value.trim() || null } });
      say("a-msg", "Saved.", "ok");
      fillForm(null);
      await loadLibrary();
    } catch (e) { say("a-msg", e.message, "err"); }
  }

  async function loadMemory() {
    const list = $("memory-list");
    list.replaceChildren();
    const items = await api("/memory");
    if (!items.length) list.append(h("li", {}, "Nothing remembered yet. Tick \"Remember this answer\" while applying."));
    for (const m of items) {
      const forget = h("button", { type: "button", class: "danger" }, "Forget");
      forget.addEventListener("click", async () => {
        try { await api(`/memory/${m.id}`, { method: "DELETE" }); await loadMemory(); }
        catch (e) { say("memory-msg", e.message, "err"); }
      });
      const scope = [m.company ? `only for ${m.company}` : "any company", m.depends_on_resume ? "tied to a resume" : null, m.depends_on_profile ? "tied to your profile" : null].filter(Boolean).join(" · ");
      list.append(h("li", {}, h("div", { class: "title" }, m.question), h("div", { class: "meta" }, scope), h("div", {}, m.answer), h("div", { class: "row" }, forget)));
    }
  }

  $("a-save").addEventListener("click", saveAnswer);
  $("a-clear").addEventListener("click", () => fillForm(null));
  Dash.register("answers", () => Promise.all([loadLibrary(), loadMemory()]));
})();
