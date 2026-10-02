"""Browser end-to-end tests: a real Chromium with the built extension, a real agent process and mock ATS sites.

Needs: the backend's dependencies, `playwright`, a Chromium (Playwright's, or CHROMIUM_PATH), and Node for the
extension build (`npm ci && npm run build:e2e` in ../extension; the fixtures build it if dist-e2e is missing).
"""

from __future__ import annotations

import functools
import glob
import http.server
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
EXT = ROOT / "extension"
SITES = Path(__file__).parent / "mock_sites"
AGENT_PORT = 8765
sys.path.insert(0, str(BACKEND))

from tests.helpers import SAMPLE_RESUME, make_pdf  # noqa: E402


def _chromium() -> str | None:
    if os.environ.get("CHROMIUM_PATH"):
        return os.environ["CHROMIUM_PATH"]
    for pattern in ("/opt/pw-browsers/chromium-*/chrome-linux*/chrome", str(Path.home() / ".cache/ms-playwright/chromium-*/chrome-linux*/chrome"),
                    str(Path.home() / "AppData/Local/ms-playwright/chromium-*/chrome-win*/chrome.exe"),
                    str(Path.home() / "Library/Caches/ms-playwright/chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium")):
        found = sorted(glob.glob(pattern))
        if found:
            return found[-1]
    return None


@pytest.fixture(scope="session")
def ext_dir() -> Path:
    out = EXT / "dist-e2e"
    if not (out / "manifest.json").exists():
        if not (EXT / "node_modules").exists() or not shutil.which("npm"):
            pytest.skip("extension is not built (run `npm ci && npm run build:e2e` in extension/)")
        subprocess.run(["npm", "run", "build:e2e"], cwd=EXT, check=True, capture_output=True)
    return out


@pytest.fixture(scope="session")
def sites():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):  # keep test output readable
            pass

    handler = functools.partial(Quiet, directory=str(SITES))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://localhost:{srv.server_address[1]}"
    srv.shutdown()


class Agent:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.base = f"http://127.0.0.1:{AGENT_PORT}"
        self.proc: subprocess.Popen | None = None
        self.token = ""

    def start(self) -> None:
        env = {**os.environ, "AUTOFILL_DATA_DIR": str(self.data_dir), "AUTOFILL_PORT": str(AGENT_PORT), "PYTHONPATH": str(BACKEND)}
        self.proc = subprocess.Popen([sys.executable, "-m", "autofill_agent"], cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                if httpx.get(f"{self.base}/api/v1/health", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        else:
            raise RuntimeError("agent did not start")
        self.token = (self.data_dir / "install_token").read_text().strip()

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def api(self, method: str, path: str, **kw):
        r = httpx.request(method, self.base + path, headers=self.headers, timeout=20, **kw)
        return r

    def upload_resume(self, name: str = "Jane.pdf", lines=None, current: bool = True) -> dict:
        r = self.api("POST", "/api/v1/resumes", files={"file": (name, make_pdf(lines or SAMPLE_RESUME))}).json()
        self.api("POST", f"/api/v1/resumes/{r['id']}/parse")
        self.api("POST", f"/api/v1/resumes/{r['id']}/verify")
        if current:
            self.api("POST", f"/api/v1/resumes/{r['id']}/set-current")
        return r


def free_port_wait(port: int) -> None:
    for _ in range(50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return
        time.sleep(0.1)


PROFILE = {
    "first_name": "Jane", "last_name": "Doe", "email": "jane.doe@example.com", "phone": "(555) 123-4567",
    "city": "Austin", "state": "TX", "country": "United States", "linkedin_url": "https://linkedin.com/in/janedoe",
    "authorized_to_work_us": True, "require_sponsorship_now": False, "require_sponsorship_future": False,
    "work_authorization_verified": True,
}


@pytest.fixture
def agent(tmp_path):
    free_port_wait(AGENT_PORT)
    a = Agent(tmp_path / "agent-data")
    a.start()
    a.api("PATCH", "/api/v1/profile", json=PROFILE)
    a.resume = a.upload_resume()
    yield a
    a.stop()


@pytest.fixture
def browser(ext_dir, tmp_path):
    from playwright.sync_api import sync_playwright

    exe = _chromium()
    if exe is None:
        pytest.skip("no Chromium found (set CHROMIUM_PATH)")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(tmp_path / "profile"), executable_path=exe, headless=False,
            args=["--headless=new", "--no-sandbox", f"--disable-extensions-except={ext_dir}", f"--load-extension={ext_dir}"],
            accept_downloads=False,
        )
        ctx.set_default_timeout(15000)
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=15000)
        ctx.sw = sw  # type: ignore[attr-defined]
        yield ctx
        ctx.close()


class Session:
    """Drives one page of the extension the way the toolbar popup and a user would."""

    def __init__(self, ctx, agent: Agent, page, url: str):
        self.ctx, self.agent, self.page, self.url = ctx, agent, page, url

    def pair(self) -> None:
        self.ctx.sw.evaluate("t => chrome.storage.local.set({token: t})", self.agent.token)

    def start(self) -> None:
        self.pair()
        self.page.goto(self.url)
        self.page.wait_for_load_state("load")
        for _ in range(60):  # the content script injects at document_idle
            try:
                self.ctx.sw.evaluate("""async (url) => {
                    const tabs = await chrome.tabs.query({});
                    const t = tabs.find(t => t.url === url);
                    await chrome.tabs.sendMessage(t.id, {type: 'start'}, {frameId: 0});
                }""", self.page.url)
                break
            except Exception:
                time.sleep(0.25)
        else:
            raise RuntimeError("content script never answered")
        self.panel.wait_for(state="attached", timeout=15000)

    @property
    def panel(self):
        return self.page.locator("[data-autofill-agent]")

    def wait_ready(self, text: str | None = None):
        self.page.locator("[data-autofill-agent] .chips").wait_for(timeout=20000)
        if text:
            self.page.locator(f"[data-autofill-agent] >> text={text}").first.wait_for(timeout=20000)

    def wait_page(self, n: int):
        """The panel has analysed page number n of the application (0-based) and shows its results."""
        self.page.locator(f"[data-autofill-agent] .wrap[data-page='{n}'][data-phase='ready']").wait_for(timeout=25000)

    def wait_filled(self):
        """The panel reports 'Filled N fields' once a fill pass and the follow-up validation are done."""
        self.page.locator("[data-autofill-agent] >> text=/Filled \\d+ field/").first.wait_for(timeout=30000)

    def shot(self, name: str) -> None:
        """Save a screenshot when E2E_SHOTS=<dir> is set (handy for reviewing the panel's look)."""
        out = os.environ.get("E2E_SHOTS")
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(Path(out) / f"{name}.png"))

    def click(self, text: str, **kw):
        self.page.locator("[data-autofill-agent] button", has_text=text).first.click(**kw)

    def panel_text(self) -> str:
        return self.page.locator("[data-autofill-agent] .body").inner_text()


@pytest.fixture
def session(browser, agent, sites):
    count = [0]

    def make(path: str) -> Session:
        page = browser.new_page()
        count[0] += 1
        # The fragment makes each tab's URL unique for the harness; the extension strips fragments from job URLs.
        return Session(browser, agent, page, f"{sites}/{path}#tab{count[0]}")

    return make
