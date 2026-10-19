from __future__ import annotations

import sys
from unittest.mock import Mock

import httpx
import pytest

from tollgate.desktop import shell


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"service": "tollgate", "status": "ok"}, True),
        ({"status": "ok"}, False),
        ({"service": "another", "status": "ok"}, False),
        ([], False),
    ],
)
def test_running_gateway_identifies_tollgate(monkeypatch, body, expected):
    get = Mock(return_value=httpx.Response(200, json=body))
    monkeypatch.setattr(httpx, "get", get)
    assert shell._running_gateway("http://127.0.0.1:8787") is expected
    assert get.call_args.kwargs["trust_env"] is False


@pytest.mark.parametrize("error", [httpx.ConnectError("closed"), ValueError("not JSON")])
def test_running_gateway_handles_unavailable_service(monkeypatch, error):
    monkeypatch.setattr(httpx, "get", Mock(side_effect=error))
    assert shell._running_gateway("http://127.0.0.1:8787") is False


@pytest.mark.parametrize("host,authority", [("0.0.0.0", "127.0.0.1"), ("::", "[::1]")])
def test_desktop_reuses_service_without_creating_or_stopping_server(monkeypatch, host, authority):
    from tollgate import config, main

    settings = config.Settings(_env_file=None, host=host, port=9000)
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    create = Mock(side_effect=AssertionError("must not start another gateway"))
    monkeypatch.setattr(main, "create_app", create)
    monkeypatch.setattr(shell, "_running_gateway", Mock(return_value=True))
    webview = Mock()
    monkeypatch.setitem(sys.modules, "webview", webview)
    shell.run_desktop()
    create.assert_not_called()
    assert webview.create_window.call_args.args[1] == f"http://{authority}:9000"
    webview.start.assert_called_once_with()


def test_desktop_rejects_busy_port_without_starting_second_gateway(monkeypatch):
    from tollgate import config, main

    monkeypatch.setattr(config, "get_settings", lambda: config.Settings(_env_file=None))
    monkeypatch.setattr(shell, "_running_gateway", Mock(return_value=False))
    socket = Mock()
    socket.__enter__ = Mock(return_value=socket)
    socket.__exit__ = Mock(return_value=False)
    socket.bind.side_effect = OSError("address in use")
    monkeypatch.setattr(shell.socket, "socket", Mock(return_value=socket))
    create = Mock()
    monkeypatch.setattr(main, "create_app", create)
    monkeypatch.setitem(sys.modules, "webview", Mock())
    with pytest.raises(RuntimeError, match="occupied"):
        shell.run_desktop()
    create.assert_not_called()


def test_desktop_stops_its_own_server_if_window_fails(monkeypatch):
    import uvicorn

    from tollgate import config, main

    monkeypatch.setattr(config, "get_settings", lambda: config.Settings(_env_file=None))
    monkeypatch.setattr(shell, "_running_gateway", Mock(side_effect=[False, True]))
    probe = Mock()
    probe.__enter__ = Mock(return_value=probe)
    probe.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(shell.socket, "socket", Mock(return_value=probe))
    monkeypatch.setattr(main, "create_app", Mock())
    monkeypatch.setattr(uvicorn, "Config", Mock())
    server = Mock(should_exit=False)
    monkeypatch.setattr(uvicorn, "Server", Mock(return_value=server))
    thread = Mock()
    monkeypatch.setattr(shell.threading, "Thread", Mock(return_value=thread))
    webview = Mock()
    webview.start.side_effect = RuntimeError("window failed")
    monkeypatch.setitem(sys.modules, "webview", webview)
    with pytest.raises(RuntimeError, match="window failed"):
        shell.run_desktop()
    assert server.should_exit is True
    thread.join.assert_called_once_with(timeout=10)
