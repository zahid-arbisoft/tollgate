# Background service

`tollgate service install` registers Tollgate for the current user, starts it
immediately, and starts it again at future sign-ins. It works with source/venv
installs and the packaged desktop executable. It does not start before sign-in
or require administrator access. Keep the installation in a permanent location.

| Platform | Manager | Registration |
|---|---|---|
| macOS | launchd LaunchAgent | `~/Library/LaunchAgents/dev.tollgate.service.plist` |
| Windows | Task Scheduler, interactive user | `Tollgate-<user SID>` task |
| Linux | systemd user service | `$XDG_CONFIG_HOME/systemd/user/tollgate.service` (defaults to `~/.config`) |

Linux needs a working systemd user session. Other init systems/platforms are not
supported by this command; supervise `tollgate serve` using your own manager.
No systemd lingering is enabled. If your account already has lingering enabled,
its user services may also run outside a login session.

## Install and configure

Stop any foreground gateway before installing. From a source checkout:

```sh
uv sync
uv run tollgate service install
uv run tollgate service status
```

On Windows use `.venv\Scripts\tollgate.exe` or the packaged `Tollgate.exe` in
place of `uv run tollgate`. For a macOS application bundle, invoke its
`Tollgate.app/Contents/MacOS/Tollgate` executable.

The service remembers the absolute interpreter/application path and working
directory. Source installs default to the current directory; packaged apps
default to the executable's directory. At startup, the normal Tollgate settings
load `.env` from that directory. Shell exports and terminal activation are **not
saved** into the service definition. Put persistent settings in that `.env`, or
use explicit installation options:

```sh
uv run tollgate service install --port 9000 --data-dir /path/to/tollgate-data \
  --working-directory /path/to/config-directory
```

`--host` is also supported. Without overrides the normal defaults apply,
including loopback binding on port 8787. Provider keys remain in Tollgate's
existing secret store; installation never copies secrets into OS registrations.
Use the same port/configuration for desktop and CLI commands as for the service.
For example, put `TOLLGATE_PORT=9000` in the shared `.env` when using a custom port.

Re-running `service install` updates the registration and restarts it. Specify
your installation options again when updating. After moving the installation,
recreating its venv, or changing installation options, run it again from the new
location. A normal in-place code or `.env` update only needs `service restart`.

## Manage and open

```sh
tollgate service status
tollgate service stop
tollgate service start
tollgate service restart
tollgate service uninstall
```

`stop` leaves sign-in startup registered. `uninstall` stops the process and
removes startup, preserving the database, keys, and logs. Uninstall the service
before removing the application or checkout. Do not run these commands with
`sudo` or under a different Windows account.

Open `http://127.0.0.1:8787` or use `tollgate desktop`. The desktop window checks
the gateway's health endpoint and reuses it; closing the window does not stop
the service. Without a running gateway, desktop mode still hosts its own server
until the window closes. An occupied port belonging to another application is
reported instead of silently starting a second gateway on a random port.

## Logs and troubleshooting

`service status` reports the OS manager's process state; it is not an HTTP
readiness check. Startup is asynchronous. If the dashboard is not available,
check the log path printed by `service status`:

- macOS: `~/Library/Logs/Tollgate/service.log`
- Windows: `%LOCALAPPDATA%\Tollgate\Logs\service.log`
- Linux: `$XDG_STATE_HOME/Tollgate/log/service.log` (usually
  `~/.local/state/Tollgate/log/service.log`)

Logs rotate at 5 MiB with three backups. launchd/systemd restart exited
processes after 10 seconds; Task Scheduler retries failures after one minute,
up to 999 retries. Windows tasks run on battery and have no execution time limit.
Task Scheduler stops tasks by terminating them; stop the gateway between active
requests when possible. On macOS/Linux, the manager sends the normal termination
signal so Uvicorn can shut down gracefully.

If there is no application log, inspect the OS manager for launch errors:

- macOS: `launchctl print gui/$(id -u)/dev.tollgate.service`. In System Settings,
  allow Tollgate's background item if macOS has disabled it. A source checkout
  in a protected Documents/Desktop folder may require macOS privacy access;
  a permanent installation outside those protected folders avoids that issue.
- Windows: Task Scheduler → `Tollgate-<user SID>` → Last Run Result / History.
  Packaged GUI executables do not print CLI output to PowerShell.
- Linux: `systemctl --user status tollgate.service` and
  `journalctl --user -u tollgate.service`. A missing user bus means this login
  session cannot manage systemd user services.

If the configured port is occupied, stop the old foreground instance and restart
the service. If the interpreter or working directory was moved/deleted, reinstall
the registration from the current installation. A locked or unavailable keychain
must be resolved in the signed-in user session.

The registrations follow the native
[Apple LaunchAgent model](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html),
[Microsoft interactive task security context](https://learn.microsoft.com/en-us/windows/win32/taskschd/security-contexts-for-running-tasks),
and [systemd service configuration](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html).
