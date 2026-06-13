#!/usr/bin/env python3
"""Start the local SaaS License Dashboard web server.

Usage:
  python scripts/dashboard/run.py
  python scripts/dashboard/run.py --port 9000

Opens http://127.0.0.1:8080 by default. Binds to localhost only — this is an
operator-local tool, not intended for network exposure.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import uvicorn  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the SaaS License Dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port (default: 8080)")
    args = parser.parse_args()

    print(f"SaaS License Dashboard → http://{args.host}:{args.port}")
    uvicorn.run("dashboard.app:app", host=args.host, port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
