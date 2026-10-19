"""Per-user login services; never install a privileged system daemon.

The OS supervises the foreground ``serve`` process. Commands use absolute paths
and argv arrays (no shell), and never copy the caller's environment or secrets.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import platformdirs

LABEL = "dev.tollgate.service"
UNIT = "tollgate.service"


class ServiceError(RuntimeError):
    """An actionable service-manager error, suitable for CLI output."""


def log_path() -> Path:
    return platformdirs.user_log_path("Tollgate", appauthor=False) / "service.log"


@dataclass(frozen=True)
class ServiceSpec:
    command: list[str]
    working_directory: Path


def make_spec(
    *,
    host: str | None = None,
    port: int | None = None,
    data_dir: Path | None = None,
    working_directory: Path | None = None,
) -> ServiceSpec:
    # Do NOT resolve symlinks: uv's venv interpreter must remain inside its venv.
    executable = Path(sys.executable).absolute()
    frozen = getattr(sys, "frozen", False)
    cwd = working_directory or (executable.parent if frozen else Path.cwd())
    cwd = cwd.expanduser().resolve()
    if not cwd.is_dir():
        raise ServiceError(f"Working directory does not exist: {cwd}")
    if sys.platform == "win32" and not frozen:
        executable = executable.with_name("pythonw.exe")
    if not executable.is_file():
        raise ServiceError(f"Service executable does not exist: {executable}")
    command = [str(executable)]
    if not frozen:
        command += ["-m", "tollgate.cli"]
    command += ["serve", "--log-file", str(log_path())]
    if host is not None:
        command += ["--host", host]
    if port is not None:
        if not 1 <= port <= 65535:
            raise ServiceError("Port must be between 1 and 65535.")
        command += ["--port", str(port)]
    if data_dir is not None:
        command += ["--data-dir", str(data_dir.expanduser().resolve())]
    return ServiceSpec(command, cwd)


def launch_agent(spec: ServiceSpec) -> bytes:
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": spec.command,
            "WorkingDirectory": str(spec.working_directory),
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": 10,
            "ProcessType": "Background",
            "Umask": 0o077,
        }
    )


def _unit_quote(value: str, *, command: bool = False) -> str:
    # systemd has its own quoting, specifiers, and ExecStart variable expansion.
    value = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    value = value.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    if command:
        value = value.replace("$", "$$")
    return f'"{value}"'


def systemd_unit(spec: ServiceSpec) -> str:
    command = " ".join(_unit_quote(arg, command=True) for arg in spec.command)
    return (
        "[Unit]\nDescription=Tollgate local LLM gateway\n\n"
        "[Service]\nType=exec\n"
        f"WorkingDirectory={_unit_quote(str(spec.working_directory))}\n"
        f"ExecStart={command}\n"
        "Restart=always\nRestartSec=10\nTimeoutStopSec=30\nUMask=0077\n\n"
        "[Install]\nWantedBy=default.target\n"
    )


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def windows_script(action: str, spec: ServiceSpec | None = None) -> str:
    """Use Task Scheduler COM to avoid localized schtasks status output.

    InteractiveToken + the current user's SID needs neither elevation nor a
    saved password. The trigger is limited to that user, even on shared PCs.
    """
    script = r"""
$ErrorActionPreference = 'Stop'
$scheduler = New-Object -ComObject 'Schedule.Service'
$scheduler.Connect()
$folder = $scheduler.GetFolder('\')
$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$name = 'Tollgate-' + $sid
$task = $null
try { $task = $folder.GetTask($name) } catch {
    if ($_.Exception.HResult -ne -2147024894 -and
        $_.Exception.InnerException.HResult -ne -2147024894) { throw }
}
"""
    if action == "status":
        return (
            script
            + """
if ($null -eq $task) { 'not installed' } else {
    $states = @('unknown', 'disabled', 'queued', 'stopped', 'running')
    $states[[int]$task.State]
    'Last task result: ' + $task.LastTaskResult
}
"""
        )
    if action in ("install", "stop", "restart", "uninstall"):
        script += """
if ($null -ne $task) {
    $task.Stop(0)
    for ($i = 0; $i -lt 100 -and $task.GetInstances(0).Count -gt 0; $i++) {
        Start-Sleep -Milliseconds 100
    }
    if ($task.GetInstances(0).Count -gt 0) { throw 'Tollgate task did not stop.' }
}
"""
    if action == "install":
        if spec is None:
            raise ValueError("install requires a service specification")
        script += """
$definition = $scheduler.NewTask(0)
$definition.RegistrationInfo.Description = 'Tollgate background gateway at sign-in'
$definition.Principal.UserId = $sid
$definition.Principal.LogonType = 3
$definition.Principal.RunLevel = 0
$trigger = $definition.Triggers.Create(9)
$trigger.UserId = $sid
$settings = $definition.Settings
$settings.Enabled = $true
$settings.StartWhenAvailable = $true
$settings.DisallowStartIfOnBatteries = $false
$settings.StopIfGoingOnBatteries = $false
$settings.ExecutionTimeLimit = 'PT0S'
$settings.MultipleInstances = 2
$settings.RestartInterval = 'PT1M'
$settings.RestartCount = 999
$exec = $definition.Actions.Create(0)
"""
        script += f"$exec.Path = {_ps_quote(spec.command[0])}\n"
        script += f"$exec.Arguments = {_ps_quote(subprocess.list2cmdline(spec.command[1:]))}\n"
        script += f"$exec.WorkingDirectory = {_ps_quote(str(spec.working_directory))}\n"
        script += "$task = $folder.RegisterTaskDefinition($name, $definition, 6, $sid, $null, 3)\n"
    if action in ("install", "start", "restart"):
        script += """
if ($null -eq $task) { throw 'Service is not installed. Run: tollgate service install' }
$task.Enabled = $true
$null = $task.Run($null)
"""
    elif action == "uninstall":
        script += "if ($null -ne $task) { $folder.DeleteTask($name, 0) }\n"
    elif action != "stop":
        raise ValueError(f"Unknown service action: {action}")
    return script


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=45,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as exc:
        raise ServiceError(f"Required service manager is unavailable: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ServiceError(f"Service manager timed out: {args[0]}") from exc
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or str(result.returncode)
        raise ServiceError(f"{args[0]} failed: {detail}")
    return result


class ServiceManager:
    def __init__(self) -> None:
        self.platform = sys.platform
        if self.platform == "darwin":
            self.path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
            self.domain = f"gui/{os.getuid()}"
            self.target = f"{self.domain}/{LABEL}"
        elif self.platform == "linux":
            config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
            if not config.is_absolute():
                raise ServiceError("XDG_CONFIG_HOME must be an absolute path.")
            self.path = config / "systemd" / "user" / UNIT
        elif self.platform == "win32":
            self.path = None  # Task Scheduler owns the registration.
        else:
            raise ServiceError(
                "Login services support macOS, Windows, and Linux with systemd. "
                "On this platform, run: tollgate serve"
            )

    def _windows(self, action: str, spec: ServiceSpec | None = None) -> str:
        return _run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                windows_script(action, spec),
            ]
        ).stdout.strip()

    def _launch_state(self) -> str | None:
        result = _run(["launchctl", "print", self.target], check=False)
        if result.returncode:
            if "Could not find service" in result.stderr:
                return None
            raise ServiceError(f"launchctl failed: {result.stderr.strip()}")
        for line in result.stdout.splitlines():
            if line.strip().startswith("state = "):
                return line.strip().removeprefix("state = ")
        return "loaded"

    def install(self, spec: ServiceSpec) -> None:
        log_path().parent.mkdir(parents=True, exist_ok=True)
        if self.platform == "win32":
            self._windows("install", spec)
            return
        content = launch_agent(spec) if self.platform == "darwin" else systemd_unit(spec).encode()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.stop()
        self.path.write_bytes(content)
        self.path.chmod(0o600)
        if self.platform == "linux":
            _run(["systemctl", "--user", "daemon-reload"])
            _run(["systemctl", "--user", "enable", "--now", UNIT])
        else:
            self.start()

    def start(self) -> None:
        if self.platform == "win32":
            self._windows("start")
            return
        if not self.path.exists():
            raise ServiceError("Service is not installed. Run: tollgate service install")
        if self.platform == "linux":
            _run(["systemctl", "--user", "start", UNIT])
        else:
            _run(["launchctl", "enable", self.target])
            state = self._launch_state()
            if state is None:
                _run(["launchctl", "bootstrap", self.domain, str(self.path)])
            elif state != "running":
                _run(["launchctl", "kickstart", self.target])

    def stop(self) -> None:
        if self.platform == "win32":
            self._windows("stop")
        elif self.platform == "darwin":
            if self._launch_state() is not None:
                _run(["launchctl", "bootout", self.target])
        elif self.path.exists():
            _run(["systemctl", "--user", "stop", UNIT])

    def restart(self) -> None:
        if self.platform == "win32":
            self._windows("restart")
        else:
            self.stop()
            self.start()

    def uninstall(self) -> None:
        if self.platform == "win32":
            self._windows("uninstall")
            return
        if self.platform == "darwin":
            self.stop()
        elif self.path.exists():
            _run(["systemctl", "--user", "disable", "--now", UNIT])
        self.path.unlink(missing_ok=True)
        if self.platform == "linux":
            _run(["systemctl", "--user", "daemon-reload"])

    def status(self) -> str:
        if self.platform == "win32":
            return self._windows("status")
        if not self.path.exists():
            return "not installed"
        if self.platform == "darwin":
            return self._launch_state() or "stopped (starts at next sign-in)"
        return _run(
            [
                "systemctl",
                "--user",
                "show",
                UNIT,
                "--property=ActiveState,SubState,UnitFileState",
            ]
        ).stdout.strip()


def configure_file_logging(path: Path, level: str) -> None:
    """Bounded logs also work in pythonw/frozen apps with no stdout/stderr."""
    from logging.config import dictConfig

    path.parent.mkdir(parents=True, exist_ok=True)
    # Restrict logs before the handler opens them on POSIX.
    with path.open("a", encoding="utf-8"):
        pass
    path.chmod(0o600)
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
            "handlers": {
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "filename": str(path),
                    "maxBytes": 5 * 1024 * 1024,
                    "backupCount": 3,
                    "encoding": "utf-8",
                    "formatter": "plain",
                }
            },
            "root": {"handlers": ["file"], "level": level.upper()},
            "loggers": {
                name: {"handlers": [], "propagate": True, "level": level.upper()}
                for name in ("uvicorn", "uvicorn.error", "uvicorn.access")
            },
        }
    )
