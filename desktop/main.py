"""Desktop launcher for reSpotIt (Windows / Linux).

Runs the FastAPI backend as a background service with a system-tray icon.
The native window opens on launch (on the main thread, as required by
pywebview); closing it hides to the tray (server keeps running). Use the tray
menu to Show / Restart / Quit.
"""

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


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ (only if not already set)."""
    if not path.is_file():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except Exception:
        pass


def find_free_port(start: int, span: int = 20) -> int:
    for p in range(start, start + span):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
            return p
        except OSError:
            continue
        finally:
            s.close()
    raise RuntimeError(f"No free port in range {start}-{start+span-1}")


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


class App:
    def __init__(self, port: int, data: Path):
        self.requested_port = port
        self.data = data
        self.port = None
        self.server = None
        self.thread = None
        self.window = None
        self.tray = None
        self.running = False

    def _env_setup(self):
        # Load .env from data dir and app dir (if present) before applying defaults.
        load_env_file(self.data / ".env")
        load_env_file(Path(sys.argv[0]).resolve().parent / ".env")
        os.environ.setdefault("DATA_DIR", str(self.data))
        os.environ.setdefault("IMAGES_DIR", str(self.data / "images"))
        os.environ.setdefault("OUTPUT_CSV", str(self.data / "spotify_albums.csv"))
        os.environ.setdefault("INPUT_CSV", str(self.data / "spotify_albums.csv"))
        os.environ.setdefault("MIGRATIONS_DIR", _migrations_dir())
        os.environ.setdefault("FRONTEND_DIST", _frontend_dist())
        if not os.getenv("DATABASE_URL"):
            os.environ["DATABASE_URL"] = f"sqlite:///{self.data / 'reSpotIt.db'}"

    def start_server(self):
        if self.running:
            return True
        self._env_setup()
        import uvicorn
        from api.main import app as fastapi_app

        self.port = find_free_port(self.requested_port)
        if self.port != self.requested_port:
            print(f"Port {self.requested_port} in use; using {self.port}. "
                  f"OAuth (registered for {self.requested_port}) will not work on this port.")

        config = uvicorn.Config(fastapi_app, host="127.0.0.1", port=self.port, log_level="info")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        if not wait_ready(self.port):
            print("Backend did not become ready in time.")
            self.stop_server()
            return False
        self.running = True
        print(f"reSpotIt running at http://127.0.0.1:{self.port}")
        return True

    def stop_server(self):
        if not self.running:
            return
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=5)
        self.running = False
        self.server = None
        self.thread = None
        print("reSpotIt stopped.")

    def restart_server(self):
        self.stop_server()
        self.start_server()
        if self.window:
            try:
                self.window.load_url(f"http://127.0.0.1:{self.port}")
                self.window.show()
            except Exception:
                pass

    def _open_window(self):
        url = f"http://127.0.0.1:{self.port}"
        try:
            import webview
            if self.window is None:
                self.window = webview.create_window("reSpotIt", url, width=1280, height=820)
            else:
                self.window.load_url(url)
                self.window.show()
        except Exception as e:
            print(f"Native window unavailable ({e}); opening browser.")
            webbrowser.open(url)

    def _show(self, icon=None, item=None):
        if self.window:
            try:
                self.window.show()
            except Exception:
                self._open_window()
        else:
            self._open_window()

    def _restart(self, icon=None, item=None):
        self.restart_server()

    def _quit(self, icon=None, item=None):
        self.stop_server()
        if self.tray:
            try:
                self.tray.stop()
            except Exception:
                pass
        if self.window:
            try:
                self.window.destroy()
            except Exception:
                pass
        sys.exit(0)

    def run_tray(self):
        try:
            import pystray
            from PIL import Image, ImageDraw
            img = Image.new("RGB", (64, 64), (25, 20, 20))
            draw = ImageDraw.Draw(img)
            draw.ellipse((16, 16, 48, 48), fill=(29, 185, 84))
            menu = pystray.Menu(
                pystray.MenuItem("Show reSpotIt", self._show, default=True),
                pystray.MenuItem("Restart server", self._restart),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._quit),
            )
            self.tray = pystray.Icon("reSpotIt", img, "reSpotIt", menu)
            self.tray.run()
        except Exception as e:
            print(f"Tray unavailable ({e}); running without tray.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
            self._quit()

    def run(self, no_window=False):
        if sys.stdout is None or sys.stderr is None:
            ld = self.data / "logs"
            ld.mkdir(parents=True, exist_ok=True)
            _lf = open(ld / "app.log", "a", encoding="utf-8")
            if sys.stdout is None:
                sys.stdout = _lf
            if sys.stderr is None:
                sys.stderr = _lf

        try:
            if not self.start_server():
                sys.exit(1)
            if no_window:
                print(f"reSpotIt running at http://127.0.0.1:{self.port}. Press Ctrl+C to stop.")
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    pass
                self.stop_server()
                return
            # tray on a daemon thread; window on the main thread (required by pywebview)
            threading.Thread(target=self.run_tray, daemon=True).start()
            self._open_window()
            try:
                import webview
                webview.start()
            except Exception as e:
                print(f"Native window unavailable ({e}); opening browser.")
                webbrowser.open(f"http://127.0.0.1:{self.port}")
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    pass
            self._quit()
        except Exception:
            import traceback
            try:
                ld = self.data / "logs"
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--data-dir", type=str, default=None)
    parser.add_argument("--no-window", action="store_true", help="run backend only")
    parser.add_argument("--no-tray", action="store_true", help="quit when window closes")
    args = parser.parse_args()

    dd = Path(args.data_dir) if args.data_dir else data_dir()
    app = App(args.port, dd)
    if args.no_tray:
        app._env_setup()
        if not app.start_server():
            sys.exit(1)
        app._open_window()
        try:
            import webview
            webview.start()
        except Exception as e:
            print(f"Native window unavailable ({e}); opening browser.")
            webbrowser.open(f"http://127.0.0.1:{app.port}")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        app.stop_server()
    else:
        app.run(no_window=args.no_window)


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    server_dir = root / "server"
    for p in (str(root), str(server_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)
    main()
