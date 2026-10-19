"""Desktop shell: reuse the background gateway, or host one for this window.

WKWebView on macOS, Edge WebView2 on Windows. The server runs in a daemon
thread bound to 127.0.0.1 (loopback only — never filtered by OS firewalls, so
this works without any admin rights on either OS).
"""

from __future__ import annotations

import logging
import socket
import threading
import time

log = logging.getLogger("tollgate.desktop")


def _running_gateway(url: str) -> bool:
    import httpx

    try:
        response = httpx.get(f"{url}/healthz", timeout=1, trust_env=False)
        body = response.json()
        return (
            response.status_code == 200
            and isinstance(body, dict)
            and body.get("service") == "tollgate"
            and body.get("status") == "ok"
        )
    except (httpx.HTTPError, ValueError):
        return False


def _open_window(webview, url: str) -> None:
    log.info("desktop window -> %s", url)
    webview.create_window("Tollgate", url, width=1280, height=860, min_size=(980, 640))
    webview.start()


def run_desktop() -> None:
    import webview

    from ..config import get_settings
    from ..main import create_app

    settings = get_settings()
    port = settings.port
    connect_host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(settings.host, settings.host)
    authority = f"[{connect_host}]" if ":" in connect_host else connect_host
    url = f"http://{authority}:{port}"
    if _running_gateway(url):
        _open_window(webview, url)
        return  # Closing a window must not stop the background service.

    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError(
                f"Port {port} is occupied but Tollgate is not ready. "
                "Check 'tollgate service status' and its logs, then try again."
            ) from exc
    settings_overrides = settings.model_copy(update={"host": "127.0.0.1", "port": port})
    app = create_app(settings_overrides)

    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level=settings.log_level.lower())
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for the server to accept connections before opening the window.
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if _running_gateway(url):
                break
            if not thread.is_alive():
                raise RuntimeError("Tollgate failed to start. Check the gateway logs.")
            time.sleep(0.1)
        else:
            raise RuntimeError("Tollgate did not become ready within 15 seconds.")
        _open_window(webview, url)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
