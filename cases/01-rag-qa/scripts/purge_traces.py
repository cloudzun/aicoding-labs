"""清理过期 trace（会审 C-02 / OB-06）。

用法：python scripts/purge_traces.py --days 7 [--dry-run]
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

TRACES = Path(__file__).resolve().parents[1] / "data" / "traces"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not TRACES.exists():
        print("无 trace 目录")
        return 0
    cutoff = time.time() - args.days * 86400
    removed = 0
    for p in TRACES.glob("*.json"):
        if p.stat().st_mtime < cutoff:
            if not args.dry_run:
                p.unlink()
            removed += 1
    print(f"{'[dry-run] 将清理' if args.dry_run else '已清理'} {removed} 个超过 {args.days} 天的 trace")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
