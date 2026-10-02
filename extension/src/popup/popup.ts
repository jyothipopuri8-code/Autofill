// Toolbar popup: pair with the local agent, pick a mode, and start the panel on the current tab.
import type { Mode } from "../shared/types";

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const send = <T = any>(msg: unknown): Promise<T> => chrome.runtime.sendMessage(msg);

function setStatus(text: string, cls: "" | "ok" | "bad" = "") {
  const el = $("status");
  el.textContent = text;
  el.className = `status ${cls}`.trim();
}

const siteId = (origin: string) => "site-" + origin.replace(/[^a-z0-9]+/gi, "_");

async function activeTab(): Promise<chrome.tabs.Tab | undefined> {
  return (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
}

async function refresh(): Promise<void> {
  const st = await send({ type: "getState" });
  $("pair").hidden = st.connected;
  $("main").hidden = !st.connected;
  if (!st.hasToken) setStatus("Not connected to the agent yet.", "");
  else if (!st.connected) setStatus(st.error || "Cannot reach the agent. Is it running?", "bad");
  else setStatus("Connected to your local agent.", "ok");
  if (st.connected) {
    if (st.settings?.mode) $<HTMLSelectElement>("mode").value = st.settings.mode;
    await listSites();
  }
}

async function listSites(): Promise<void> {
  const ul = $("sites");
  ul.textContent = "";
  const { origins = [] } = await chrome.permissions.getAll();
  const mine = origins.filter((o) => !/^http:\/\/127\.0\.0\.1:8765\//.test(o) && o !== "<all_urls>");
  if (!mine.length) { const li = document.createElement("li"); li.textContent = "None yet"; ul.append(li); return; }
  for (const o of mine) {
    const li = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = o.replace(/\/\*$/, "");
    const rm = document.createElement("button");
    rm.textContent = "Remove";
    rm.addEventListener("click", async () => {
      try { await chrome.scripting.unregisterContentScripts({ ids: [siteId(o.replace(/\/\*$/, ""))] }); } catch { /* not registered */ }
      await chrome.permissions.remove({ origins: [o] });
      await listSites();
    });
    li.append(name, rm);
    ul.append(li);
  }
}

async function start(): Promise<void> {
  const note = $("startnote");
  note.textContent = "";
  const tab = await activeTab();
  let url: URL | null = null;
  try { url = tab?.url ? new URL(tab.url) : null; } catch { /* ignore */ }
  if (!tab?.id || !url || !/^https?:$/.test(url.protocol)) { note.textContent = "Open a job application page in this tab first."; return; }
  const origin = url.origin;
  const pattern = `${origin}/*`;
  if (!(await chrome.permissions.contains({ origins: [pattern] }))) {
    const granted = await chrome.permissions.request({ origins: [pattern] });
    if (!granted) { note.textContent = `Without access to ${url.hostname} the agent cannot read the form.`; return; }
  }
  // Keep the panel available on the later pages of the same application.
  try {
    const have = await chrome.scripting.getRegisteredContentScripts({ ids: [siteId(origin)] });
    if (!have.length) await chrome.scripting.registerContentScripts([{ id: siteId(origin), matches: [pattern], js: ["content.js"], runAt: "document_idle", persistAcrossSessions: true }]);
  } catch (e) { /* the page-level start below still works */ }
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
    await chrome.tabs.sendMessage(tab.id, { type: "start" }, { frameId: 0 });
    window.close();
  } catch (e) {
    note.textContent = "Could not start on this page. Try reloading it.";
  }
}

$("connect").addEventListener("click", async () => {
  const token = $<HTMLInputElement>("token").value.trim();
  if (!token) return;
  setStatus("Connecting…");
  const r = await send({ type: "setToken", token });
  $<HTMLInputElement>("token").value = "";
  if (!r?.ok) setStatus(r?.error || r?.data?.detail || "That token was not accepted.", "bad");
  await refresh();
});
$("start").addEventListener("click", () => void start());
$("toggle").addEventListener("click", async () => {
  const tab = await activeTab();
  if (tab?.id) await chrome.tabs.sendMessage(tab.id, { type: "toggle" }, { frameId: 0 }).catch(() => { $("startnote").textContent = "Nothing is running on this page yet."; });
});
$("mode").addEventListener("change", async (e) => { await send({ type: "setMode", mode: (e.target as HTMLSelectElement).value as Mode }); });
$("open").addEventListener("click", () => void chrome.tabs.create({ url: "http://127.0.0.1:8765/ui/" }));
$("disconnect").addEventListener("click", async () => { await send({ type: "clearToken" }); await refresh(); });

void refresh();
