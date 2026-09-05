from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.monitoring.health_check import database_available


def main() -> int:
    parser = argparse.ArgumentParser(description="Check that the signal engine SQLite database is reachable")
    parser.add_argument("--database", default="data/signal_engine.db")
    args = parser.parse_args()
    if database_available(args.database):
        print(f"healthy: database reachable at {args.database}")
        return 0
    print(f"unhealthy: database unavailable at {args.database}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
