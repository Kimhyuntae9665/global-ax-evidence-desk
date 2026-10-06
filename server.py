"""Run with: python server.py (Python 3.10+, no third-party dependencies)."""

import argparse
from pathlib import Path

from axdesk import Desk
from axdesk.http import make_server


def main():
    parser = argparse.ArgumentParser(description="Synthetic supplier energy evidence desk")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    desk = Desk(root / "work" / "runtime" / "desk.sqlite3", root / "data")
    server = make_server(desk, root / "web", args.port)
    print(f"Synthetic AX Evidence Desk: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
