"""校验锚点集：每条 SQL 必须能执行，并补上 columns/rows/gold_hash。

用法：python -m scripts.verify_anchor
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "aicoding.db"
ANCHOR = ROOT / "eval" / "anchor_set.jsonl"


def norm(rows):
    out = []
    for r in rows:
        out.append([round(v, 2) if isinstance(v, float) else v for v in r])
    return out


def main() -> int:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = [json.loads(x) for x in ANCHOR.read_text(encoding="utf-8").splitlines() if x.strip()]
    failed = []
    for r in rows:
        try:
            cur = conn.execute(r["sql"])
            cols = [d[0] for d in cur.description]
            data = norm(cur.fetchall())
        except Exception as exc:  # noqa: BLE001
            failed.append((r["qid"], str(exc)))
            continue
        r["columns"] = cols
        r["row_count"] = len(data)
        r["gold_sample"] = data[:5]
        r["gold_hash"] = hashlib.sha256(
            json.dumps([cols, data], ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()[:16]
    conn.close()

    ANCHOR.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    if failed:
        print("[FAIL] 锚点 SQL 执行失败：")
        for qid, err in failed:
            print(f"  {qid}: {err}")
        return 2
    print(f"[done] {len(rows)} 条锚点全部可执行，已写入 {ANCHOR}")
    for r in rows[:3]:
        print(f"  {r['qid']} rows={r['row_count']} sample={r['gold_sample']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
