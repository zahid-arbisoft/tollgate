# Installing Tollgate on Windows

All paths below are **per-user — no administrator rights anywhere**.

## Option 1 — Installer (recommended)

Once a release is published (GitHub Actions builds them from tags):

1. Download `tollgate-setup-<version>.exe` from the
   [Releases](../../releases) page.
2. Run it. It installs into `%LOCALAPPDATA%\Programs\Tollgate` with **no UAC
   prompt** (Inno Setup with `PrivilegesRequired=lowest`), adds a Start-menu
   entry and an optional desktop shortcut. Leave **Run Tollgate in the background
   when I sign in** checked to install the background service.
3. Launch **Tollgate** — a native window opens (Edge WebView2, preinstalled on
   current Windows 10/11; if missing, install the
   [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
   per-user).

Uninstall from *Settings → Apps*, per-user like any other app. The installer
stops the service before upgrades and removes it during uninstall.

## Option 2 — Portable zip

Download `tollgate-portable-<version>-windows-x64.zip`, unzip anywhere
(Desktop is fine), run `Tollgate.exe`. Nothing is installed, no registry
changes. This is also the fallback if SmartScreen/AV objects to the installer:
SmartScreen will warn on unsigned binaries — choose *More info → Run anyway*
(code signing is a later step).

## Option 3 — From source (works today, before any release)

Needs Python 3.12+ (the python.org installer has a per-user "Install just for
me" mode — no admin). Then:

```powershell
git clone <repo> tollgate
cd tollgate
# with uv (simplest):  winget install astral-sh.uv  (or pipx install uv)
uv sync --extra desktop
uv run tollgate desktop      # native window
# or plain pip:
pip install -e ".[desktop]"
tollgate desktop
```

Headless variant: `tollgate serve` then browse to `http://127.0.0.1:8787`
(admin token: `tollgate key admin-token`).

## Run in the background at sign-in

Close any foreground gateway, then run from PowerShell:

```powershell
# Source installation:
.venv\Scripts\tollgate.exe service install
.venv\Scripts\tollgate.exe service status
# Packaged installation (run from its installation directory):
.\Tollgate.exe service install
```

This registers a Task Scheduler task for your account and starts it immediately.
It uses your signed-in session and requires neither administrator rights nor a
stored Windows password. Source installs use `pythonw.exe`, so no terminal window
appears. The native desktop window connects to the running gateway, and closing
the window leaves it running.

Use `service restart` after updating, or `service uninstall` to remove automatic
startup before deleting/uninstalling the application. Packaged Windows builds
have no console output; inspect Task Scheduler's `Tollgate-<your SID>` task and
`%LOCALAPPDATA%\Tollgate\Logs\service.log` for status/errors.
See [background service setup](background-service.md) for configuration details.

## Where your data lives

`%LOCALAPPDATA%\Tollgate` (database + encrypted secrets). API keys are stored
in Windows Credential Manager when available, with an encrypted-file fallback.

## Networking notes

- The app binds `127.0.0.1` by default → **no Windows Firewall prompt**, since
  loopback traffic is never filtered.
- Binding LAN-wide (`tollgate serve --host 0.0.0.0`) makes it reachable from
  other machines; Windows may then ask to allow Python/Tollgate through the
  firewall — on a locked-down machine where you can't approve that, use an
  outbound tunnel (see [remote-and-benchmarks.md](remote-and-benchmarks.md)).
- In a UTM VM reaching a Tollgate on the Mac host: see
  [remote-and-benchmarks.md](remote-and-benchmarks.md).
