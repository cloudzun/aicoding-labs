"""gold 变更后刷新问句：SQL 未变的保留原问句，变了的清空待重出。"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "eval" / "gold_cases.jsonl"
GOLDEN = ROOT / "eval" / "golden_set.jsonl"


def main() -> int:
    old: dict[str, dict] = {}
    if GOLDEN.exists():
        for line in GOLDEN.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                old[r["qid"]] = r

    rows = [json.loads(x) for x in GOLD.read_text(encoding="utf-8").splitlines() if x.strip()]
    changed = 0
    for r in rows:
        o = old.get(r["qid"])
        if o and o.get("sql") == r["sql"] and o.get("question"):
            r["question"] = o["question"]
        else:
            r["question"] = ""
            changed += 1
    GOLDEN.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print(f"[done] {len(rows)} 条，需重出问句 {changed} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
