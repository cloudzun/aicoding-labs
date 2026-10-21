"""四道安全闸的对抗测试（AC-07 证据）。

用法：python -m scripts.test_safety
输出：evidence/safety.json；全部通过退出码 0
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.safety import guarded_query, validate_sql  # noqa: E402

CASES = [
    ("正常查询", "SELECT COUNT(*) AS cnt FROM fact_customer".replace("fact_customer", "dim_customer"), "ok"),
    ("写操作 DELETE", "DELETE FROM fact_order", "reject"),
    ("写操作 UPDATE", "UPDATE fact_bill SET amount_due=0", "reject"),
    ("DDL DROP", "DROP TABLE fact_order", "reject"),
    ("多语句注入", "SELECT * FROM fact_order; DROP TABLE fact_order", "reject"),
    ("系统表", "SELECT * FROM sqlite_master", "reject"),
    ("PRAGMA", "PRAGMA table_info(fact_order)", "reject"),
    ("未授权表", "SELECT * FROM secret_table", "reject"),
    ("ATTACH 外库", "ATTACH DATABASE 'x.db' AS x", "reject"),
    ("UNION 系统表", "SELECT name FROM dim_customer UNION SELECT name FROM sqlite_master", "reject"),
    ("大结果集截断", "SELECT * FROM fact_ticket", "truncated"),
    ("注释绕过尝试", "SELECT * FROM fact_order -- ; DELETE FROM fact_order", "ok_or_reject"),
]


def main() -> int:
    results = []
    failed = 0
    for name, sql, expect in CASES:
        v = validate_sql(sql)
        if not v.ok:
            got = "reject"
            detail = v.reason
        else:
            r = guarded_query(sql, max_rows=1000, timeout_s=10)
            if not r["ok"]:
                got = "reject"
                detail = r["reason"]
            elif r["truncated"]:
                got = "truncated"
                detail = f"rows={len(r['rows'])}"
            else:
                got = "ok"
                detail = f"rows={len(r['rows'])}"
        ok = got == expect or (expect == "ok_or_reject" and got in ("ok", "reject"))
        if not ok:
            failed += 1
        results.append({"case": name, "sql": sql, "expect": expect, "got": got, "detail": detail, "pass": ok})
        print(f"[{'PASS' if ok else 'FAIL'}] {name:14s} expect={expect:13s} got={got:10s} {detail[:60]}")

    out = ROOT / "evidence" / "safety.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"cases": results, "failed": failed}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(CASES) - failed}/{len(CASES)} 通过 → {out}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
