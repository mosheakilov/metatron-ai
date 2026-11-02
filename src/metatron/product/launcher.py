"""Start METATRON: WhatsApp gateway + local server + outbox, then open the dashboard.

    python -m metatron.product.launcher [--no-browser] [--port 8765]

The installer's shortcut runs this with pythonw (no console). A tray icon offers "open" and
"quit". Starting it a second time only opens the dashboard of the running instance.
"""

from __future__ import annotations

import argparse
import atexit
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

import httpx
import uvicorn

from metatron.product.gateway import GatewayClient
from metatron.product.server import Ctx, create_app
from metatron.product.settings import Settings

APP_PORT, GATEWAY_PORT = 8765, 8766


def _gateway_dir() -> Path:
    # installed: <app>/gateway next to <app>/runtime; development: <repo>/gateway
    here = Path(__file__).resolve()
    for base in [Path(sys.prefix).parent, *here.parents]:
        if (base / "gateway" / "index.js").exists():
            return base / "gateway"
    raise FileNotFoundError("gateway/index.js not found")


def _node() -> str:
    bundled = Path(sys.prefix).parent / "node" / "node.exe"
    return str(bundled) if bundled.exists() else (shutil.which("node") or "node")


def _running(port: int) -> bool:
    try:
        return httpx.get(f"http://127.0.0.1:{port}/api/state", timeout=1).status_code == 200
    except httpx.HTTPError:
        return False


def start_gateway(settings: Settings, app_port: int, gw_port: int) -> subprocess.Popen:
    gdir = _gateway_dir()
    env = {**os.environ, "GATEWAY_PORT": str(gw_port), "GATEWAY_TOKEN": settings.data["secret"],
           "WA_AUTH_DIR": str(settings.folder / "wa-auth"), "PARENT_PID": str(os.getpid()),
           "INBOUND_URL": f"http://127.0.0.1:{app_port}/internal/wa/inbound"}
    logf = open(settings.folder / "logs" / "gateway.log", "a", encoding="utf-8")  # noqa: SIM115
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen([_node(), str(gdir / "index.js")], cwd=gdir, env=env, stdout=logf,
                            stderr=subprocess.STDOUT, creationflags=flags)
    atexit.register(proc.terminate)
    return proc


def _watch_gateway(proc_ref: list, settings: Settings, app_port: int, gw_port: int) -> None:
    while True:  # the gateway must stay up for replies to arrive
        time.sleep(5)
        if proc_ref[0].poll() is not None:
            logging.warning("gateway exited (%s); restarting", proc_ref[0].returncode)
            proc_ref[0] = start_gateway(settings, app_port, gw_port)


def _tray(url: str, server: uvicorn.Server) -> bool:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        return False
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, 60, 60), 14, fill=(37, 99, 235))
    d.polygon([(32, 14), (50, 32), (32, 50), (14, 32)], fill="white")

    def quit_app(icon, _item):
        server.should_exit = True
        icon.stop()

    icon = pystray.Icon("METATRON", img, "METATRON", menu=pystray.Menu(
        pystray.MenuItem("פתיחת METATRON", lambda *_: webbrowser.open(url), default=True),
        pystray.MenuItem("יציאה", quit_app)))
    threading.Thread(target=icon.run, daemon=True).start()
    return True


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=APP_PORT)
    ap.add_argument("--gateway-port", type=int, default=GATEWAY_PORT)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)
    url = f"http://127.0.0.1:{args.port}"
    if _running(args.port):
        webbrowser.open(url)
        return

    settings = Settings()
    (settings.folder / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(
        settings.folder / "logs" / "metatron.log", maxBytes=2_000_000, backupCount=3,
        encoding="utf-8")], format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    logging.getLogger("httpx").setLevel(logging.WARNING)  # the outbox polls the gateway often
    proc = [start_gateway(settings, args.port, args.gateway_port)]
    threading.Thread(target=_watch_gateway, args=(proc, settings, args.port, args.gateway_port),
                     daemon=True).start()
    ctx = Ctx(settings, GatewayClient(args.gateway_port, settings.data["secret"]))
    ctx.outbox.start()
    server = uvicorn.Server(uvicorn.Config(create_app(ctx), host="127.0.0.1", port=args.port,
                                           log_config=None, access_log=False))
    _tray(url, server)
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    server.run()
    ctx.outbox.stop()
    proc[0].terminate()


if __name__ == "__main__":
    main()
