// Profile and sensitive-question settings.
"use strict";
(() => {
  const { api, h, say } = Dash;
  const $ = (id) => document.getElementById(id);

  const TRI = [["", "Not set (ask me)"], ["true", "Yes"], ["false", "No"]];
  const GROUPS = [
    ["Name", [["first_name", "First name"], ["middle_name", "Middle name"], ["last_name", "Last name"], ["preferred_name", "Preferred name"], ["pronouns", "Pronouns"]]],
    ["Contact", [["email", "Email"], ["phone", "Phone"], ["phone_country_code", "Phone country code (+1)"],
      ["phone_device_type", "Phone type", "select", [["", "Not set"], ["mobile", "Mobile"], ["home", "Home"], ["work", "Work"]]], ["phone_extension", "Extension"],
      ["linkedin_url", "LinkedIn URL"], ["github_url", "GitHub URL"], ["portfolio_url", "Portfolio URL"], ["website_url", "Website URL"]]],
    ["Address", [["address_line1", "Address line 1"], ["address_line2", "Address line 2"], ["city", "City"], ["state", "State / region"], ["country", "Country"], ["postal_code", "Postal code"]]],
    ["Work authorization", [["authorized_to_work_us", "Authorized to work in the US", "tri"], ["require_sponsorship_now", "Need sponsorship now", "tri"], ["require_sponsorship_future", "Need sponsorship in the future", "tri"],
      ["work_authorization_verified", "I have checked these three answers and they are accurate", "check"]]],
    ["Preferences", [["willing_to_relocate", "Willing to relocate", "tri"], ["travel_willingness", "Travel willingness"], ["remote_preference", "Open to remote", "tri"],
      ["hybrid_preference", "Open to hybrid", "tri"], ["onsite_preference", "Open to on-site", "tri"], ["available_start_date", "Available start date", "date"], ["referral_source", "How you heard about jobs"]]],
  ];
  const SENSITIVE_LABEL = {
    gender: "Gender", race: "Race", ethnicity: "Ethnicity", hispanic_latino: "Hispanic or Latino", disability_status: "Disability status",
    medical_accommodation: "Medical accommodation", veteran_status: "Veteran status",
  };

  function control(spec, value) {
    const [name, label, kind, opts] = spec;
    if (kind === "tri" || kind === "select") {
      const sel = h("select", { "data-f": name, class: "tri" });
      for (const [v, t] of (kind === "tri" ? TRI : opts)) sel.append(h("option", { value: v }, t));
      sel.value = value === true ? "true" : value === false ? "false" : value == null ? "" : String(value);
      return h("label", {}, label, sel);
    }
    if (kind === "check") {
      const box = h("input", { type: "checkbox", "data-f": name });
      box.checked = !!value;
      return h("label", { class: "check" }, box, label);
    }
    const input = h("input", { type: kind === "date" ? "date" : "text", "data-f": name });
    input.value = value == null ? "" : String(value);
    return h("label", {}, label, input);
  }

  async function loadProfile() {
    const p = await api("/profile");
    const form = $("profile-form");
    form.replaceChildren();
    for (const [title, fields] of GROUPS) {
      const grid = h("div", { class: "grid" });
      for (const f of fields) grid.append(control(f, p[f[0]]));
      form.append(h("fieldset", {}, h("legend", {}, title), grid));
    }
  }

  function readProfile() {
    const out = {};
    for (const el of document.querySelectorAll("#profile-form [data-f]")) {
      const name = el.dataset.f;
      if (el.type === "checkbox") out[name] = el.checked;
      else if (el.tagName === "SELECT" && (el.value === "true" || el.value === "false")) out[name] = el.value === "true";
      else out[name] = el.value.trim() === "" ? null : el.value.trim();
    }
    return out;
  }

  async function saveProfile() {
    try {
      await api("/profile", { method: "PATCH", json: readProfile() });
      say("profile-msg", "Saved.", "ok");
      await loadProfile();
    } catch (e) { say("profile-msg", e.message, "err"); }
  }

  async function loadSensitive() {
    const list = $("sensitive-list");
    list.replaceChildren();
    for (const p of await api("/profile/sensitive")) {
      const policy = h("select", { "aria-label": SENSITIVE_LABEL[p.field] + " policy" },
        h("option", { value: "ASK_ME" }, "Ask me each time"), h("option", { value: "AUTOFILL" }, "Always answer"), h("option", { value: "NEVER_FILL" }, "Never fill"));
      policy.value = p.policy;
      const value = h("input", { type: "text", placeholder: "Exact answer, e.g. Decline to self-identify", "aria-label": SENSITIVE_LABEL[p.field] + " answer" });
      value.value = p.value || "";
      const sync = () => { value.hidden = policy.value !== "AUTOFILL"; };
      policy.addEventListener("change", sync);
      sync();
      const save = h("button", { type: "button" }, "Save");
      save.addEventListener("click", async () => {
        try {
          await api(`/profile/sensitive/${p.field}`, { method: "PUT", json: { policy: policy.value, value: policy.value === "AUTOFILL" ? value.value.trim() : null } });
          say("sensitive-msg", `${SENSITIVE_LABEL[p.field]} saved.`, "ok");
        } catch (e) { say("sensitive-msg", e.message, "err"); }
      });
      list.append(h("li", {}, h("div", { class: "title" }, SENSITIVE_LABEL[p.field] || p.field), h("div", { class: "row" }, policy, value, save)));
    }
  }

  $("profile-save").addEventListener("click", saveProfile);
  Dash.register("profile", async () => { say("profile-msg", ""); await Promise.all([loadProfile(), loadSensitive()]); });
})();
