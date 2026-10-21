"""端到端冒烟：正常合同 / 有缺陷合同 / 语义规则 / 注入防御。

用法：python -m scripts.smoke [--semantic]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline import review  # noqa: E402

CASES = [("CT001", "正常合同"), ("CT003", "有缺陷合同")]


def main() -> int:
    use_sem = "--semantic" in sys.argv
    for cid, label in CASES:
        r = review(ROOT / "data" / "contracts" / f"{cid}.docx", with_semantic=use_sem)
        print("=" * 78)
        print(f"{cid} {label} | 页(估)={r['pages_estimated']} 段={r['n_paras']} 耗时={r['meta']['elapsed_ms']}ms")
        print("  摘要:", r["summary"], "| 覆盖率:", r["coverage"]["rules_checked"], "/", r["coverage"]["rules_total"],
              "| 未取得依据:", r["coverage"]["not_detected"])
        for f in r["findings"][:8]:
            loc = f["locator"]
            print(f"  [{f['level']}] {f['rule_id']} {f['title']} · {f['category']} · "
                  f"{'段' + str(loc['para']) if loc else '—'} · {f['reason'][:60]}")
        print("  时间拆解:", r["meta"]["timings_ms"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
