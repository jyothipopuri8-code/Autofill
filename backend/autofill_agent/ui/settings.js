// Operating mode, local AI status, export and erase.
"use strict";
(() => {
  const { api, h, say } = Dash;
  const $ = (id) => document.getElementById(id);
  const MODES = [
    ["SAFE", "Safe (recommended)", "Nothing is filled until you click Fill. Everything else is shown for review."],
    ["STANDARD", "Standard", "Fields the agent is highly confident about, and that are not sensitive, are filled automatically. Everything else waits for you."],
    ["MANUAL_ASSIST", "Manual assist", "The agent only prepares answers. You insert each field yourself."],
  ];

  async function load() {
    const s = await api("/settings");
    const box = $("mode-box");
    box.replaceChildren(h("legend", {}, "Mode"));
    for (const [value, title, text] of MODES) {
      const radio = h("input", { type: "radio", name: "mode", value });
      radio.checked = s.mode === value;
      radio.addEventListener("change", async () => {
        try { await api("/settings", { method: "PUT", json: { mode: value } }); say("mode-msg", `Mode set to ${title}.`, "ok"); }
        catch (e) { say("mode-msg", e.message, "err"); }
      });
      box.append(h("label", { class: "check roomy" }, radio, h("span", {}, h("strong", {}, title + " "), text)));
    }
    $("ai-status").textContent = s.ai.enabled
      ? `Local AI is on (model ${s.ai.model}). It only drafts custom answers from your verified resume, and every draft is checked and shown for your review.`
      : "Local AI is off. To turn it on, run Ollama on this computer and start the agent with AUTOFILL_OLLAMA_ENABLED=true. Nothing is ever sent to the internet.";
  }

  async function exportData() {
    try {
      const res = await fetch("/api/v1/data/export", { headers: { Authorization: "Bearer " + sessionStorage.getItem("agentToken") } });
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      const url = URL.createObjectURL(await res.blob());
      const a = h("a", { href: url, download: "autofill-agent-export.json" });
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
      say("erase-msg", "Exported.", "ok");
    } catch (e) { say("erase-msg", e.message, "err"); }
  }

  async function erase() {
    const scope = $("erase-scope").value;
    if (!confirm(`Permanently erase: ${$("erase-scope").selectedOptions[0].textContent}? This cannot be undone.`)) return;
    try {
      const r = await api("/data/delete", { method: "POST", json: { scope, confirm: $("erase-confirm").value } });
      $("erase-confirm").value = "";
      say("erase-msg", "Erased: " + Object.entries(r.deleted).map(([k, v]) => `${v} ${k.replace(/_/g, " ")}`).join(", "), "ok");
    } catch (e) { say("erase-msg", e.message, "err"); }
  }

  $("export").addEventListener("click", exportData);
  $("erase").addEventListener("click", erase);
  Dash.register("settings", () => { say("erase-msg", ""); return load(); });
})();
