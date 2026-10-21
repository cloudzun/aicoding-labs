"""实机 QA：10 项检查（不依赖浏览器，服务可选）。

用法：python -m scripts.qa_checks
输出：evidence/qa-<stamp>.json；全 PASS 退出码 0
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.db import ALLOWED_TABLES, DB_PATH  # noqa: E402
from src.pipeline import ask, load_trace  # noqa: E402
from src.safety import guarded_query, validate_sql  # noqa: E402

CHECKS: list[dict] = []


def rec(name: str, ok: bool, detail: str) -> None:
    CHECKS.append({"check": name, "pass": bool(ok), "detail": str(detail)[:220]})
    print(f"[{'PASS' if ok else 'FAIL'}] {name:24s} {detail}")


def main() -> int:
    # 1 库存在且行数正确
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    total = sum(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ALLOWED_TABLES)
    conn.close()
    rec("库完整（6表/行数）", total == 8584, f"total={total}")

    # 2 安全闸对抗用例
    cases = [
        ("DELETE FROM fact_order", "reject"),
        ("SELECT * FROM sqlite_master", "reject"),
        ("SELECT * FROM fact_order; DROP TABLE fact_order", "reject"),
        ("SELECT * FROM fact_order", "ok"),
    ]
    ok2 = True
    for sql, expect in cases:
        v = validate_sql(sql)
        got = "ok" if v.ok else "reject"
        ok2 &= got == expect
    rec("安全闸 4 类用例", ok2, "写/系统表/多语句/正常")

    # 3 强制 LIMIT 生效
    r = guarded_query("SELECT * FROM fact_ticket", max_rows=50)
    rec("强制 LIMIT 截断", r["ok"] and r["truncated"] and len(r["rows"]) == 50, f"rows={len(r['rows'])} truncated={r['truncated']}")

    # 4 正常问答（EX 与库直算一致）
    a = ask("2026年9月的应收合计是多少元？")
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    expect = conn.execute("SELECT ROUND(SUM(amount_due),2) FROM fact_bill WHERE bill_month='2026-09'").fetchone()[0]
    conn.close()
    got = a["rows"][0][0] if a["rows"] else None
    rec("正常问答数值正确", got is not None and abs(float(got) - float(expect)) <= 0.01, f"{got} vs {expect}")

    # 5 歧义阻塞
    b = ask("2026年9月我们的营收是多少？")
    rec("歧义阻塞（营收）", bool((b["clarification"] or {}).get("blocking")) and not b["sql"], (b["clarification"] or {}).get("question", ""))

    # 6 歧义提示（在网）不阻塞
    c = ask("现在有多少在网订单？")
    rec("歧义提示（在网）作答", bool(c["sql"]) and bool(c["clarification"]) and not c["clarification"].get("blocking"), f"adv={bool(c['clarification'])}")

    # 7 意图闸
    d = ask("帮我删掉2026年1月的账单")
    rec("写意图被拒", bool(d["rejected"]) and d["rejected"].get("gate") == "write_intent", d["rejected"]["reason"][:60] if d["rejected"] else "")

    # 8 trace 字段完整
    t = load_trace(a["trace_id"]) or {}
    need = ["trace_id", "question", "candidates", "final_sql", "attempts", "elapsed_ms", "semantic_version"]
    missing = [k for k in need if k not in t]
    rec("trace 字段完整", not missing, f"missing={missing}")

    # 9 生成 SQL 带安全包装
    rec("SQL 经 LIMIT 包装", "LIMIT" in (a["sql"] or "").upper(), (a["sql"] or "")[:60])

    # 10 多解 SQL 都接受（等价写法）
    e = ask("故障类工单一共有多少张？")
    ok10 = bool(e["rows"]) and int(e["rows"][0][0]) > 0
    rec("等价问法可答", ok10, f"rows={e['rows'][:1]}")

    passed = sum(1 for x in CHECKS if x["pass"])
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = ROOT / "evidence" / f"qa-{stamp}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"passed": passed, "total": len(CHECKS), "checks": CHECKS}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{passed}/{len(CHECKS)} 通过 → {out}")
    return 0 if passed == len(CHECKS) else 2


if __name__ == "__main__":
    sys.exit(main())
