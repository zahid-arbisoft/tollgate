"""Service definitions/lifecycle with isolated files and mocked OS managers.

No test registers a real login item, opens a secret store, or contacts a model.
"""

from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from tollgate import service
from tollgate.cli import app


@pytest.fixture
def spec(tmp_path):
    return service.ServiceSpec(
        [str(tmp_path / "App Space" / "python"), "-m", "tollgate.cli", "serve"],
        tmp_path / "Working & configuration",
    )


@pytest.fixture
def native(monkeypatch, tmp_path):
    """Select a target OS without replacing pathlib's host path implementation."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr(service, "log_path", lambda: tmp_path / "logs" / "service.log")
    run = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr(service, "_run", run)

    def make(platform):
        monkeypatch.setattr(service.sys, "platform", platform)
        monkeypatch.setattr(service.os, "getuid", lambda: 501, raising=False)
        return service.ServiceManager(), run

    return make


def test_launch_agent_has_absolute_argv_and_login_restart(spec):
    config = plistlib.loads(service.launch_agent(spec))
    assert config["ProgramArguments"] == spec.command
    assert config["WorkingDirectory"] == str(spec.working_directory)
    assert config["RunAtLoad"] and config["KeepAlive"]
    assert config["ThrottleInterval"] == 10
    assert "EnvironmentVariables" not in config


def test_systemd_escapes_paths_without_shell_interpretation(tmp_path):
    spec = service.ServiceSpec(
        ['/a b/50%/$HOME/"python"', "serve", "--host", "127.0.0.1"],
        tmp_path / 'a %h $HOME "quoted"',
    )
    unit = service.systemd_unit(spec)
    assert 'ExecStart="/a b/50%%/$$HOME/\\"python\\"" "serve"' in unit
    assert 'a %%h $HOME \\"quoted\\"' in unit
    assert "Restart=always" in unit
    assert "WantedBy=default.target" in unit
    assert "User=" not in unit


def test_windows_interactive_task_and_quoting(tmp_path):
    spec = service.ServiceSpec(
        [r"C:\Program Files\Tollgate\Tollgate.exe", "serve", "--data-dir", "C:\\O'Brien\\"],
        tmp_path / "O'Brien & Co",
    )
    script = service.windows_script("install", spec)
    assert "$scheduler.GetFolder('\\')" in script
    assert "LogonType = 3" in script  # interactive token, not a stored password
    assert "RunLevel = 0" in script
    assert "$trigger.UserId = $sid" in script
    assert "$name = 'Tollgate-' + $sid" in script
    assert "ExecutionTimeLimit = 'PT0S'" in script
    assert "DisallowStartIfOnBatteries = $false" in script
    assert "StopIfGoingOnBatteries = $false" in script
    assert "MultipleInstances = 2" in script  # ignore duplicate starts
    assert "O''Brien & Co" in script
    assert "RestartCount = 999" in script
    assert script.index("$task.Stop(0)") < script.index("RegisterTaskDefinition")
    assert "GetInstances(0).Count" in script  # wait for old process before restart


@pytest.mark.parametrize("action", ["start", "stop", "restart", "status", "uninstall"])
def test_windows_lifecycle_uses_same_user_task(action):
    script = service.windows_script(action)
    assert "$folder.GetTask($name)" in script
    assert "GetCurrent().User.Value" in script
    if action == "uninstall":
        assert "$folder.DeleteTask($name, 0)" in script
    if action == "status":
        assert "$task.State" in script and "LastTaskResult" in script
    assert "RegisterTaskDefinition" not in script


def test_make_spec_keeps_venv_interpreter_and_explicit_overrides(monkeypatch, tmp_path):
    interpreter = tmp_path / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    monkeypatch.setattr(sys, "executable", str(interpreter))
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setattr(service, "log_path", lambda: tmp_path / "logs" / "service.log")
    spec = service.make_spec(
        host="127.0.0.1", port=9000, data_dir=tmp_path / "data", working_directory=tmp_path
    )
    assert spec.command[:4] == [str(interpreter), "-m", "tollgate.cli", "serve"]
    assert spec.command[-6:] == [
        "--host",
        "127.0.0.1",
        "--port",
        "9000",
        "--data-dir",
        str(tmp_path / "data"),
    ]


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_make_spec_does_not_resolve_venv_symlink(monkeypatch, tmp_path):
    real = tmp_path / "base-python"
    real.touch()
    link = tmp_path / "venv-python"
    link.symlink_to(real)
    monkeypatch.setattr(sys, "executable", str(link))
    assert service.make_spec(working_directory=tmp_path).command[0] == str(link)


def test_windows_source_uses_pythonw(monkeypatch, tmp_path):
    pythonw = tmp_path / "pythonw.exe"
    pythonw.touch()
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    monkeypatch.setattr(sys, "platform", "win32")
    assert service.make_spec(working_directory=tmp_path).command[0] == str(pythonw)
    pythonw.unlink()
    with pytest.raises(service.ServiceError, match="pythonw"):
        service.make_spec(working_directory=tmp_path)


def test_frozen_command_invokes_executable_directly(monkeypatch, tmp_path):
    exe = tmp_path / "Tollgate.exe"
    exe.touch()
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    spec = service.make_spec()
    assert spec.command[:2] == [str(exe), "serve"]
    assert spec.working_directory == tmp_path


def test_install_rejects_missing_working_directory(tmp_path):
    with pytest.raises(service.ServiceError, match="Working directory"):
        service.make_spec(working_directory=tmp_path / "missing")


def test_launchd_install_start_stop_and_uninstall(native, spec):
    manager, run = native("darwin")
    monkey_state = Mock(return_value=None)
    manager._launch_state = monkey_state
    manager.install(spec)
    assert plistlib.loads(manager.path.read_bytes())["ProgramArguments"] == spec.command
    assert ["launchctl", "enable", manager.target] in [c.args[0] for c in run.call_args_list]
    assert run.call_args.args[0] == ["launchctl", "bootstrap", "gui/501", str(manager.path)]
    monkey_state.return_value = "running"
    manager.start()
    assert run.call_args.args[0] == ["launchctl", "enable", manager.target]
    manager.stop()
    assert run.call_args.args[0] == ["launchctl", "bootout", manager.target]
    assert manager.path.exists()  # stopping does not disable next sign-in
    manager.uninstall()
    assert not manager.path.exists()


def test_launchd_distinguishes_absent_job_from_permission_failure(native):
    manager, run = native("darwin")
    run.return_value = subprocess.CompletedProcess([], 113, "", "Could not find service abc")
    assert manager._launch_state() is None
    run.return_value = subprocess.CompletedProcess([], 1, "", "Operation not permitted")
    with pytest.raises(service.ServiceError, match="Operation not permitted"):
        manager._launch_state()
    run.return_value = subprocess.CompletedProcess([], 0, "job {\n\tstate = running\n}", "")
    assert manager._launch_state() == "running"


def test_linux_lifecycle(native, spec):
    manager, run = native("linux")
    assert manager.status() == "not installed"
    with pytest.raises(service.ServiceError, match="not installed"):
        manager.start()
    manager.install(spec)
    assert manager.path.read_text() == service.systemd_unit(spec)
    assert run.call_args.args[0] == ["systemctl", "--user", "enable", "--now", service.UNIT]
    run.reset_mock()
    manager.restart()
    assert [c.args[0] for c in run.call_args_list] == [
        ["systemctl", "--user", "stop", service.UNIT],
        ["systemctl", "--user", "start", service.UNIT],
    ]
    manager.uninstall()
    assert not manager.path.exists()
    assert run.call_args.args[0] == ["systemctl", "--user", "daemon-reload"]
    run.reset_mock()
    manager.uninstall()
    assert run.call_count == 1  # idempotent reload, no missing-unit stop/disable


def test_linux_failed_manager_is_not_reported_as_success(native, spec):
    manager, run = native("linux")
    run.side_effect = service.ServiceError("user bus unavailable")
    with pytest.raises(service.ServiceError, match="user bus unavailable"):
        manager.install(spec)


def test_windows_manager_passes_script_as_single_argument(native, spec):
    manager, run = native("win32")
    manager.install(spec)
    args = run.call_args.args[0]
    assert args[:4] == ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command"]
    assert args[4] == service.windows_script("install", spec)


def test_unsupported_platform(native):
    with pytest.raises(service.ServiceError, match="Linux with systemd"):
        native("freebsd")


def test_native_command_errors_are_actionable(monkeypatch):
    run = Mock(side_effect=FileNotFoundError)
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(service.ServiceError, match="unavailable: systemctl"):
        service._run(["systemctl", "--user", "status"])
    run.side_effect = subprocess.TimeoutExpired("systemctl", 45)
    with pytest.raises(service.ServiceError, match="timed out"):
        service._run(["systemctl"])
    run.side_effect = None
    run.return_value = subprocess.CompletedProcess([], 1, "", "Access denied")
    with pytest.raises(service.ServiceError, match="Access denied"):
        service._run(["systemctl"])
    assert run.call_args.kwargs["timeout"] == 45
    assert "shell" not in run.call_args.kwargs


@pytest.mark.parametrize("action", ["start", "stop", "restart", "status", "uninstall"])
def test_cli_management_does_not_load_settings(monkeypatch, action):
    from tollgate import config, service_cli

    monkeypatch.setattr(config, "get_settings", Mock(side_effect=AssertionError("settings loaded")))
    manager = Mock()
    manager.status.return_value = "running"
    monkeypatch.setattr(service_cli, "ServiceManager", Mock(return_value=manager))
    result = CliRunner().invoke(app, ["service", action])
    assert result.exit_code == 0, result.output
    getattr(manager, action).assert_called_once_with()


def test_cli_install_and_failures(monkeypatch, tmp_path):
    from tollgate import service_cli

    manager = Mock()
    monkeypatch.setattr(service_cli, "ServiceManager", Mock(return_value=manager))
    result = CliRunner().invoke(
        app, ["service", "install", "--port", "9000", "--working-directory", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "sign-in" in result.output
    assert "9000" in manager.install.call_args.args[0].command
    manager.install.side_effect = service.ServiceError("manager failed")
    result = CliRunner().invoke(app, ["service", "install"])
    assert result.exit_code == 1
    assert "manager failed" in result.output
    result = CliRunner().invoke(app, ["service", "install", "--port", "0"])
    assert result.exit_code == 2


def test_serve_uses_file_logs_and_explicit_data_dir(monkeypatch, tmp_path):
    import uvicorn

    from tollgate import main

    create = Mock(return_value=object())
    run = Mock()
    log = Mock()
    monkeypatch.setattr(main, "create_app", create)
    monkeypatch.setattr(uvicorn, "run", run)
    monkeypatch.setattr(service, "configure_file_logging", log)
    result = CliRunner().invoke(
        app,
        [
            "serve",
            "--port",
            "9000",
            "--data-dir",
            str(tmp_path / "data"),
            "--log-file",
            str(tmp_path / "service.log"),
        ],
    )
    assert result.exit_code == 0, result.output
    settings = create.call_args.args[0]
    assert settings.data_dir == tmp_path / "data"
    assert settings.port == 9000
    assert run.call_args.kwargs["log_config"] is None  # no console logger in pythonw
    log.assert_called_with(tmp_path / "service.log", settings.log_level)


def test_rotating_logging_without_console(tmp_path):
    # Separate interpreter keeps dictConfig from replacing pytest's own handlers.
    script = """
import logging
import sys
from pathlib import Path
from tollgate.service import configure_file_logging
path = Path(sys.argv[1])
sys.stdout = sys.stderr = None
configure_file_logging(path, 'INFO')
handler = logging.getLogger().handlers[0]
handler.maxBytes = 200
for i in range(20):
    logging.getLogger('uvicorn.error').info('rotation smoke check %s', i)
logging.shutdown()
assert path.exists()
assert Path(str(path) + '.1').exists()
assert 'rotation smoke check 19' in path.read_text()
"""
    subprocess.run([sys.executable, "-c", script, str(tmp_path / "service.log")], check=True)


def test_settings_errors_are_logged_before_app_startup(monkeypatch, tmp_path):
    import logging

    from tollgate import config, main

    monkeypatch.setattr(config, "Settings", Mock(side_effect=ValueError("invalid configuration")))
    monkeypatch.setattr(service, "configure_file_logging", Mock())
    create = Mock()
    monkeypatch.setattr(main, "create_app", create)
    log_exception = Mock()
    monkeypatch.setattr(logging.getLogger("tollgate"), "exception", log_exception)
    result = CliRunner().invoke(
        app, ["serve", "--log-file", str(tmp_path / "log"), "--data-dir", str(tmp_path)]
    )
    assert result.exit_code == 1
    log_exception.assert_called_once_with("Gateway startup failed")
    create.assert_not_called()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell parser")
def test_windows_scripts_parse_without_running_tasks(spec):
    # Parse only: never invoke the generated script or connect to Task Scheduler.
    for action in ("install", "start", "stop", "restart", "status", "uninstall"):
        script = service.windows_script(action, spec)
        parser = (
            "$ErrorActionPreference = 'Stop'; "
            "[void][scriptblock]::Create(" + service._ps_quote(script) + ")"
        )
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", parser],
            check=True,
            capture_output=True,
            timeout=15,
        )


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS plist validator")
def test_launch_agent_passes_native_plist_validation(spec, tmp_path):
    path = tmp_path / "test.plist"
    path.write_bytes(service.launch_agent(spec))
    subprocess.run(["plutil", "-lint", str(path)], check=True, capture_output=True, timeout=10)
