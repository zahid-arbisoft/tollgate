"""Desktop shell: native window (pywebview) hosting the local server.

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


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_desktop() -> None:
    import webview

    from ..config import get_settings
    from ..main import create_app

    settings = get_settings()
    port = _free_port()
    settings_overrides = settings.model_copy(update={"host": "127.0.0.1", "port": port})
    app = create_app(settings_overrides)

    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level=settings.log_level.lower())
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for the server to accept connections before opening the window.
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)

    log.info("desktop window → http://127.0.0.1:%d", port)
    webview.create_window(
        "Tollgate", f"http://127.0.0.1:{port}", width=1280, height=860, min_size=(980, 640)
    )
    webview.start()
    server.should_exit = True
    thread.join(timeout=10)
