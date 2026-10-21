"""端到端冒烟：正常 / 歧义 / 越权三类问句。

用法：python -m scripts.smoke
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline import ask  # noqa: E402

CASES = [
    "2026年9月的应收合计是多少元？",
    "杭州有多少家状态正常的客户？",
    "2026年9月我们的营收是多少？",
    "帮我删掉2026年1月的账单",
    "2026年9月故障工单里高优的有多少张？",
]


def main() -> int:
    for q in CASES:
        r = ask(q)
        print("=" * 78)
        print("Q:", q)
        if r["clarification"]:
            print("  [澄清]", r["clarification"]["question"], "→", r["clarification"]["options"])
            print("  rows:", r["row_count"], "sql:", r["sql"])
            continue
        if r["rejected"]:
            print("  [拒绝]", r["rejected"].get("reason", "")[:120])
            print("  sql:", (r["rejected"].get("sql") or "")[:120])
            continue
        print("  attempts:", r["attempts"], "rows:", r["row_count"], "truncated:", r["truncated"])
        print("  cols:", r["columns"])
        print("  sample:", r["rows"][:3])
        print("  chart:", r["chart"]["type"], "|", r["chart"]["reason"])
        print("  timings:", r["timings_ms"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
