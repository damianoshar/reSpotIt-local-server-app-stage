"""Desktop launcher for reSpotIt (Windows / Linux)."""

import argparse
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

DEFAULT_PORT = int(os.getenv("PORT", "8888"))


def data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / "reSpotIt" / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "logs").mkdir(exist_ok=True)
    (d / "images").mkdir(exist_ok=True)
    return d


def pick_port(requested: int) -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", requested))
        return requested
    except OSError:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


def wait_ready(port: int, timeout: float = 30.0) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--data-dir", type=str, default=None)
    parser.add_argument("--no-window", action="store_true", help="run backend only")
    args = parser.parse_args()

    # Redirect stdio in windowed (PyInstaller) mode so failures are logged.
    if sys.stdout is None or sys.stderr is None:
        ld = data_dir() / "logs"
        ld.mkdir(parents=True, exist_ok=True)
        _lf = open(ld / "app.log", "a", encoding="utf-8")
        if sys.stdout is None:
            sys.stdout = _lf
        if sys.stderr is None:
            sys.stderr = _lf

    dd = Path(args.data_dir) if args.data_dir else data_dir()
    os.environ.setdefault("DATA_DIR", str(dd))
    os.environ.setdefault("IMAGES_DIR", str(dd / "images"))
    os.environ.setdefault("OUTPUT_CSV", str(dd / "spotify_albums.csv"))
    os.environ.setdefault("INPUT_CSV", str(dd / "spotify_albums.csv"))
    os.environ.setdefault("MIGRATIONS_DIR", _migrations_dir())
    os.environ.setdefault("FRONTEND_DIST", _frontend_dist())

    # OAuth requires a fixed port matching the registered redirect URI.
    if args.port == DEFAULT_PORT:
        try:
            _s = socket.socket()
            _s.bind(("127.0.0.1", DEFAULT_PORT))
            _s.close()
        except OSError:
            print(f"Port {DEFAULT_PORT} is in use. The Spotify OAuth redirect URI is registered for "
                  f"http://127.0.0.1:{DEFAULT_PORT}/api/v1/auth/callback, so the app cannot start on "
                  f"another port. Free port {DEFAULT_PORT} or pass --port <n> (OAuth will not work).")
            sys.exit(1)
    port = pick_port(args.port)
    if port != args.port:
        print(f"Port {args.port} in use; using {port}.")

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        db_path = dd / "reSpotIt.db"
        db_url = f"sqlite:///{db_path}"
        os.environ["DATABASE_URL"] = db_url

    import uvicorn
    from api.main import app

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="info")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    if not wait_ready(port):
        print("Backend did not become ready in time.")
        server.should_exit = True
        sys.exit(1)

    url = f"http://127.0.0.1:{port}"

    if args.no_window:
        print(f"reSpotIt running at {url}. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        server.should_exit = True
        return

    try:
        import webview
        window = webview.create_window("reSpotIt", url, width=1280, height=820)
        webview.start()
    except Exception as e:
        print(f"Native window unavailable ({e}); opening browser.")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    server.should_exit = True
    thread.join(timeout=5)


def main():
    try:
        _main()
    except Exception:
        import traceback
        try:
            ld = data_dir() / "logs"
            ld.mkdir(parents=True, exist_ok=True)
            with open(ld / "app.log", "a", encoding="utf-8") as f:
                traceback.print_exc(file=f)
        except Exception:
            pass
        raise


def _migrations_dir() -> str:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and (Path(meipass) / "migrations").is_dir():
        return str(Path(meipass) / "migrations")
    here = Path(__file__).resolve().parent.parent
    if (here / "server" / "migrations").is_dir():
        return str(here / "server" / "migrations")
    if (here / "migrations").is_dir():
        return str(here / "migrations")
    return "/app/migrations"


def _frontend_dist() -> str:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and (Path(meipass) / "frontend" / "dist").is_dir():
        return str(Path(meipass) / "frontend" / "dist")
    here = Path(__file__).resolve().parent.parent
    for c in (here / "server" / "frontend" / "dist", here / "frontend" / "dist"):
        if c.is_dir():
            return str(c)
    return ""


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    server_dir = root / "server"
    for p in (str(root), str(server_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)
    main()
