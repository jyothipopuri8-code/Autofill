// Service worker: the only place that talks to the local agent. It holds the install token,
// restricts which API calls the page-side script may make, and keeps per-tab session state.
import type { ApiRequest, ApiResponse, TabState } from "../shared/types";
import { allowed } from "./allowlist";

const BASE = "http://127.0.0.1:8765";

async function token(): Promise<string> {
  const { token } = await chrome.storage.local.get("token");
  return typeof token === "string" ? token : "";
}

function b64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

export async function callApi(req: { method: string; path: string; body?: unknown; binary?: boolean }, bypassAllowList = false): Promise<ApiResponse> {
  if (typeof req?.path !== "string" || typeof req?.method !== "string" || req.path.length > 400) return { ok: false, status: 0, data: null, error: "Request not permitted" };
  if (!bypassAllowList && !allowed(req.method, req.path)) return { ok: false, status: 0, data: null, error: "Request not permitted" };
  const t = await token();
  if (!t) return { ok: false, status: 401, data: null, error: "Not connected: add your installation token in the extension popup" };
  try {
    const res = await fetch(BASE + req.path, {
      method: req.method,
      headers: { Authorization: `Bearer ${t}`, ...(req.body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: req.body !== undefined ? JSON.stringify(req.body) : undefined,
    });
    const headers: Record<string, string> = {};
    res.headers.forEach((v, k) => (headers[k] = v));
    if (req.binary && res.ok) return { ok: true, status: res.status, data: null, headers, base64: b64(await res.arrayBuffer()) };
    const text = await res.text();
    let data: any = null;
    try { data = text ? JSON.parse(text) : null; } catch { data = text; }
    return { ok: res.ok, status: res.status, data, headers };
  } catch (e) {
    return { ok: false, status: 0, data: null, error: "Cannot reach the agent. Is it running on 127.0.0.1:8765?" };
  }
}

// --- per-tab session state (survives service-worker restarts) -----------------

const tabKey = (tabId: number) => `tab:${tabId}`;
async function getTab(tabId: number): Promise<TabState> {
  const r = await chrome.storage.session.get(tabKey(tabId));
  return (r[tabKey(tabId)] as TabState) ?? null;
}
async function setTab(tabId: number, st: TabState) {
  if (st) await chrome.storage.session.set({ [tabKey(tabId)]: st });
  else await chrome.storage.session.remove(tabKey(tabId));
}
chrome.tabs.onRemoved.addListener((id) => { void setTab(id, null); });

// --- messages -----------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg: any, sender, sendResponse) => {
  (async () => {
    switch (msg?.type) {
      case "api": {
        // Only our own extension pages may bypass the allow-list; content scripts have a sender.tab.
        sendResponse(await callApi(msg as ApiRequest, !sender.tab));
        return;
      }
      case "setToken": {
        if (sender.tab) { sendResponse({ ok: false }); return; }
        await chrome.storage.local.set({ token: String(msg.token || "").trim() });
        const r = await callApi({ method: "GET", path: "/api/v1/status" }, true);
        if (!r.ok) await chrome.storage.local.remove("token");
        sendResponse(r);
        return;
      }
      case "clearToken": {
        if (!sender.tab) await chrome.storage.local.remove("token");
        sendResponse({ ok: true });
        return;
      }
      case "getState": {
        const r = (await token()) ? await callApi({ method: "GET", path: "/api/v1/status" }, true) : null;
        const settings = r?.ok ? await callApi({ method: "GET", path: "/api/v1/settings" }, true) : null;
        sendResponse({ hasToken: !!(await token()), connected: !!r?.ok, error: r && !r.ok ? r.error || r.data?.detail : null, settings: settings?.data ?? null });
        return;
      }
      case "setMode": {
        if (sender.tab) { sendResponse({ ok: false }); return; }
        sendResponse(await callApi({ method: "PUT", path: "/api/v1/settings", body: { mode: msg.mode } }, true));
        return;
      }
      case "getTabState": {
        const id = sender.tab?.id ?? msg.tabId;
        sendResponse(id != null ? await getTab(id) : null);
        return;
      }
      case "setTabState": {
        const id = sender.tab?.id ?? msg.tabId;
        if (id != null) await setTab(id, msg.state ?? null);
        sendResponse({ ok: true });
        return;
      }
      default:
        sendResponse({ ok: false, error: "unknown message" });
    }
  })();
  return true; // async response
});
