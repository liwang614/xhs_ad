from __future__ import annotations

import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
GUI_APP = os.path.join(PROJECT_ROOT, "gui", "app.py")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = "12700"


def main() -> int:
    host = os.getenv("GUI_HOST", DEFAULT_HOST)
    port = os.getenv("GUI_PORT", DEFAULT_PORT)

    cmd = [
        sys.executable, "-m", "streamlit", "run", GUI_APP,
        "--server.address", host,
        "--server.port", port,
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
    print(f"启动 GUI: http://{host}:{port}")
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
