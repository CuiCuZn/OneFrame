"""Local launcher: serves the API + built SPA on a single port and opens a browser."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def running_instance(host: str, port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=1.5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return bool(payload.get("ok"))
    except Exception:
        return False


def free_port(start: int) -> int:
    for port in range(start, start + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise SystemExit(f"端口 {start}-{start + 29} 都被占用，请先关闭占用程序")


def main() -> None:
    parser = argparse.ArgumentParser(description="OneFrame local server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    import uvicorn

    from app import config

    if not args.reload and running_instance(args.host, args.port):
        url = f"http://{args.host}:{args.port}"
        print(f"\n  OneFrame is already running at {url}\n  Open it in the browser, or stop it with stop.bat first.\n")
        if os.environ.get("ONEFRAME_NO_BROWSER") != "1":
            webbrowser.open(url)
        return

    dist = ROOT.parent / "frontend" / "dist"
    if not dist.exists():
        print("提示：尚未构建前端（frontend/dist 不存在）。接口仍可用。")
        print("      在 frontend 目录执行 npm install && npm run build 后重启即可。")

    port = args.port if args.reload else free_port(args.port)
    url = f"http://{args.host}:{port}"
    open_browser = not args.no_browser and os.environ.get("ONEFRAME_NO_BROWSER") != "1"
    if open_browser:
        threading.Timer(1.6, lambda: webbrowser.open(url)).start()
    config.ensure_dirs()
    pid_file = config.DATA_DIR / "oneframe.pid"
    pid_file.write_text(str(os.getpid()), encoding="ascii")
    print(f"\n  一格 OneFrame · {url}\n  数据目录：{config.DATA_DIR}\n  按 Ctrl+C 停止\n")
    try:
        uvicorn.run(
            "app.main:app",
            host=args.host,
            port=port,
            reload=args.reload,
            reload_dirs=[str(ROOT / "app")] if args.reload else None,
            log_level="info",
        )
    finally:
        with contextlib.suppress(OSError):
            pid_file.unlink()


if __name__ == "__main__":
    main()
