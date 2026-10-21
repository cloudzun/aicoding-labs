"""数据完整性断言：确认 10 类埋点真实存在（不是生成器自说自话）。

用法：python -m scripts.verify_db [--json]
退出码：0 全部命中；2 有断言失败（可直接接 CI / 环 0 门禁）
"""

from __future__ import annotations
import sys as _sys

# 干净 Windows 的默认代码页可能不是 UTF-8；中文 print 会抛 UnicodeEncodeError。
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "aicoding.db"

# (埋点, 检测 SQL, 期望关系, 期望值)
CHECKS = [
    ("A 重复客户组", "SELECT COUNT(*) FROM (SELECT customer_name FROM dim_customer GROUP BY customer_name HAVING COUNT(*)>1)", "==", 3),
    ("B 地市变体数", "SELECT COUNT(DISTINCT city) FROM dim_customer", ">=", 9),
    ("C 同名产品组", "SELECT COUNT(*) FROM (SELECT product_name FROM dim_product GROUP BY product_name HAVING COUNT(*)>1)", ">=", 3),
    ("D 等级为空", "SELECT COUNT(*) FROM dim_customer WHERE customer_level IS NULL", ">=", 1),
    ("E 未来订单", "SELECT COUNT(*) FROM fact_order WHERE order_date>'2026-12-31'", "==", 2),
    ("F 工单未响应", "SELECT COUNT(*) FROM fact_ticket WHERE first_response_at IS NULL", ">=", 50),
    ("F2 工单未解决", "SELECT COUNT(*) FROM fact_ticket WHERE resolved_at IS NULL", ">=", 50),
    (
        "G SLA矛盾",
        "SELECT COUNT(*) FROM fact_ticket WHERE (sla_flag='N' AND (julianday(resolved_at)-julianday(created_at))*24<=4) "
        "OR (sla_flag='Y' AND (julianday(resolved_at)-julianday(created_at))*24>4)",
        ">=",
        20,
    ),
    ("H 应收不符", "SELECT COUNT(*) FROM fact_bill b JOIN fact_order o ON o.order_id=b.order_id "
     "WHERE ABS(b.amount_due-(ROUND(o.monthly_fee*o.discount_rate,2)+b.adjustment))>0.01", "==", 8),
    ("I 负调整", "SELECT COUNT(*) FROM fact_bill WHERE adjustment<0", ">=", 20),
    (
        "J 退订后出账",
        "SELECT COUNT(*) FROM fact_bill b JOIN fact_order o ON o.order_id=b.order_id "
        "WHERE o.cancel_date IS NOT NULL AND b.bill_month>=substr(o.cancel_date,1,7)",
        ">=",
        3,
    ),
]


def main() -> int:
    conn = sqlite3.connect(DB)
    results = []
    failed = 0
    for name, sql, op, expect in CHECKS:
        try:
            got = conn.execute(sql).fetchone()[0]
        except Exception as exc:  # noqa: BLE001
            results.append({"check": name, "got": None, "expect": f"{op}{expect}", "pass": False, "error": str(exc)})
            failed += 1
            continue
        ok = got == expect if op == "==" else got >= expect
        results.append({"check": name, "got": got, "expect": f"{op} {expect}", "pass": bool(ok)})
        if not ok:
            failed += 1
        print(f"[{'PASS' if ok else 'FAIL'}] {name:16s} got={got:<6} expect {op} {expect}")

    counts = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("dim_customer", "dim_product", "dim_employee", "fact_order", "fact_ticket", "fact_bill")
    }
    conn.close()
    print("\n表行数：", counts, "合计", sum(counts.values()))

    out = ROOT / "evidence" / "db-verify.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"row_counts": counts, "checks": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[evidence] {out}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
