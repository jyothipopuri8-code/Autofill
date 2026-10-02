# Running on Windows (Phase 42)

> **Status:** `install.ps1`, `package.ps1 -Exe`, the standalone `autofill-agent.exe` (starts, answers on 127.0.0.1, serves the review page) and
> the backend tests all passed on a GitHub-hosted Windows runner (CI job `Windows scripts`, 2026-10-02). They have **not** yet been run on a
> personal Windows computer, and `autostart.ps1`, `uninstall.ps1`, the browser extension on Windows Chrome/Edge, and SmartScreen behaviour
> have not been exercised anywhere. Treat the first run on your own computer as the test and tell us what breaks.

Everything runs for the current user. No administrator rights are needed and nothing listens on any address except `127.0.0.1:8765`.

## Option A: from source (recommended while testing)

Needs Python 3.11+ (<https://www.python.org/downloads/>, tick "Add python.exe to PATH") and, to build the extension, Node.js 20+.

```powershell
git clone https://github.com/jyothipopuri8-code/autofill.git
cd autofill
scripts\windows\install.ps1          # creates .venv, installs the agent, builds the extension
scripts\windows\start-agent.bat      # or: scripts\windows\start-agent.ps1
```

If PowerShell refuses to run scripts, run them as `powershell -ExecutionPolicy Bypass -File scripts\windows\install.ps1` (applies to that one run only).

Then:

1. Open `chrome://extensions` (or `edge://extensions`), switch on **Developer mode**, **Load unpacked**, choose `extension\dist`.
2. Print the pairing token: `.venv\Scripts\python.exe -m autofill_agent token`, and paste it into the extension popup.
3. Open the review page <http://127.0.0.1:8765/ui/> to upload and verify your resume and fill in your profile.

The extension ID is fixed, so the agent already accepts it; there is nothing to configure.

## Start automatically

```powershell
scripts\windows\autostart.ps1 -Enable    # puts a shortcut in your Startup folder
scripts\windows\autostart.ps1 -Disable
scripts\windows\autostart.ps1            # shows the current state
```

## Option B: standalone agent (no Python needed on the target machine)

```powershell
scripts\windows\package.ps1 -Exe
```

Creates `release\autofill-extension.zip`, `release\autofill-agent-windows.zip` and `release\SHA256SUMS.txt`. Unzip the agent anywhere and
run `autofill-agent.exe`; unzip the extension and load it as above. Windows SmartScreen or antivirus may warn about an unsigned
executable. The build is not code-signed, so check the SHA-256 against `SHA256SUMS.txt` if you received it from someone else.

## Where your data lives

`%LOCALAPPDATA%\AutofillAgent` (database, resumes, logs, `install_token`). Override with the `AUTOFILL_DATA_DIR` environment variable.
Back it up like any personal document folder; it is not encrypted (see [SECURITY.md](SECURITY.md)).

## Uninstall

```powershell
scripts\windows\uninstall.ps1                 # removes autostart, keeps your data
scripts\windows\uninstall.ps1 -DeleteData     # also deletes your data, after you type DELETE
```

Then delete the folder and remove the extension from `chrome://extensions`.

## What still needs a Windows run

- `start-agent.ps1`, `autostart.ps1` and `uninstall.ps1` on a real Windows 10 and 11 user (CI covers install, packaging and the standalone agent only).
- Owner-only permissions on the data folder (the code sets POSIX modes; on Windows it relies on the default per-user ACL of `%LOCALAPPDATA%`).
- How SmartScreen and antivirus treat the unsigned `autofill-agent.exe` (the build itself passes in CI).
- Chrome and Edge loading the same `dist` folder.
