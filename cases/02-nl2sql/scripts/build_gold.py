"""生成 gold 用例：模板化 SQL + 参数网格 → 执行得标准结果集。

设计（核心，勿改）：**先写 SQL 并执行拿到 gold 结果，再让 LLM 生成自然语言问题。**
这样"问题与标准答案"不可能错位；EX 才有意义。

用法：python -m scripts.build_gold
产出：eval/gold_cases.jsonl、eval/gold_manifest.json
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "aicoding.db"
OUT = ROOT / "eval" / "gold_cases.jsonl"
MANIFEST = ROOT / "eval" / "gold_manifest.json"

QUOTA = {"single_hop": 40, "two_join": 30, "three_join": 20, "aggregate": 30, "time_window": 15, "negation_null": 15}

CITIES = ["杭州", "宁波", "温州", "金华", "绍兴"]
INDS = ["制造", "金融", "政府", "教育", "医疗", "交通", "能源"]

# (split, sql 模板, [{参数}...], 问题要点提示)
TEMPLATES: list[tuple[str, str, list[dict], str]] = [
    # ---------- 单表 ----------
    ("single_hop", "SELECT customer_id, customer_name FROM dim_customer WHERE industry='{ind}' AND status='正常' ORDER BY customer_id LIMIT 20",
     [{"ind": x} for x in INDS], "列出某行业的正常状态客户"),
    ("single_hop", "SELECT COUNT(*) AS cnt FROM dim_customer WHERE customer_level='{lvl}'",
     [{"lvl": x} for x in ("A", "B", "C")], "统计某等级客户数"),
    ("single_hop", "SELECT product_id, product_name, standard_price FROM dim_product WHERE product_type='{pt}' AND status='在售' ORDER BY standard_price DESC LIMIT 10",
     [{"pt": x} for x in ("专线", "云", "IDC")], "某类产品在售清单按月费降序"),
    ("single_hop", "SELECT order_id, monthly_fee FROM fact_order WHERE status='{st}' AND monthly_fee>{fee} ORDER BY monthly_fee DESC LIMIT 10",
     [{"st": s, "fee": f} for s in ("在网", "已退订") for f in (3000, 5000)], "某状态订单中月费超过阈值的清单"),
    ("single_hop", "SELECT ticket_id, created_at, urgency FROM fact_ticket WHERE ticket_type='{tt}' AND urgency='高' ORDER BY created_at DESC LIMIT 10",
     [{"tt": x} for x in ("故障", "投诉", "开通")], "某类高优工单最近十条"),
    ("single_hop", "SELECT emp_name, team FROM dim_employee WHERE role='{role}' ORDER BY emp_id LIMIT 15",
     [{"role": x} for x in ("客户经理", "维护班组", "客服")], "某角色员工与班组"),
    ("single_hop", "SELECT COUNT(*) AS cnt FROM dim_customer WHERE city LIKE '{city}%'",
     [{"city": c} for c in CITIES], "某地市客户数（注意地市写法不统一）"),
    ("single_hop", "SELECT COUNT(*) AS cnt FROM fact_ticket WHERE ticket_type='故障' AND created_at>='{d}'",
     [{"d": x} for x in ("2026-01-01", "2026-04-01", "2026-07-01")], "某日之后故障工单数"),
    ("single_hop", "SELECT ticket_id, ticket_type, created_at FROM fact_ticket WHERE first_response_at IS NULL LIMIT 10",
     [{}], "从未响应过的工单"),
    ("single_hop", "SELECT product_name, bandwidth_mbps FROM dim_product WHERE product_type='专线' AND bandwidth_mbps>=1000 ORDER BY bandwidth_mbps DESC LIMIT 10",
     [{}], "千兆及以上专线产品"),
    # ---------- 两表 ----------
    ("two_join", "SELECT c.customer_id, ROUND(SUM(o.monthly_fee*o.discount_rate),2) AS fee FROM fact_order o JOIN dim_customer c ON c.customer_id=o.customer_id WHERE c.city LIKE '{city}%' AND o.cancel_date IS NULL GROUP BY c.customer_id ORDER BY fee DESC, c.customer_id LIMIT 10",
     [{"city": c} for c in CITIES], "某地市在网订单的折扣后月费合计 Top10 客户"),
    ("two_join", "SELECT c.industry, COUNT(*) AS cnt FROM fact_ticket t JOIN dim_customer c ON c.customer_id=t.customer_id WHERE t.ticket_type='{tt}' GROUP BY c.industry ORDER BY cnt DESC",
     [{"tt": x} for x in ("故障", "投诉", "开通")], "某类工单按行业分布"),
    ("two_join", "SELECT p.product_name, COUNT(*) AS cnt FROM fact_order o JOIN dim_product p ON p.product_id=o.product_id WHERE p.product_type='{pt}' GROUP BY p.product_name ORDER BY cnt DESC LIMIT 10",
     [{"pt": x} for x in ("专线", "云", "IDC")], "某类产品被订购最多的名称 Top10"),
    ("two_join", "SELECT c.customer_name, ROUND(AVG((julianday(t.resolved_at)-julianday(t.created_at))*24),2) AS hrs FROM fact_ticket t JOIN dim_customer c ON c.customer_id=t.customer_id WHERE t.resolved_at IS NOT NULL AND t.ticket_type='故障' GROUP BY c.customer_name ORDER BY hrs DESC LIMIT 5",
     [{}], "故障工单平均解决时长最长的 5 个客户"),
    ("two_join", "SELECT e.emp_name, COUNT(*) AS cnt FROM fact_order o JOIN dim_employee e ON e.emp_id=o.sales_emp_id GROUP BY e.emp_name ORDER BY cnt DESC LIMIT 5",
     [{}], "下单最多的销售 Top5"),
    ("two_join", "SELECT c.customer_level, COUNT(DISTINCT o.order_id) AS cnt FROM fact_order o JOIN dim_customer c ON c.customer_id=o.customer_id WHERE o.order_date>='{d}' GROUP BY c.customer_level",
     [{"d": x} for x in ("2026-01-01", "2026-06-01")], "某日期之后各等级客户的新增订单数"),
    ("two_join", "SELECT p.product_type, COUNT(*) AS cnt FROM fact_ticket t JOIN dim_product p ON p.product_id=t.product_id WHERE t.urgency='高' GROUP BY p.product_type",
     [{}], "高优工单按产品类型分布"),
    ("two_join", "SELECT c.city, COUNT(*) AS cnt FROM dim_customer c JOIN fact_order o ON o.customer_id=c.customer_id WHERE o.cancel_date IS NOT NULL GROUP BY c.city ORDER BY cnt DESC",
     [{}], "各地市已退订订单数"),
    # ---------- 三表 ----------
    ("three_join", "SELECT c.customer_name, p.product_name, ROUND(SUM(b.amount_due),2) AS due FROM fact_bill b JOIN dim_customer c ON c.customer_id=b.customer_id JOIN dim_product p ON p.product_id=b.product_id WHERE b.bill_month='{m}' GROUP BY c.customer_name, p.product_name ORDER BY due DESC LIMIT 10",
     [{"m": x} for x in ("2026-09", "2026-08", "2026-07", "2026-06")], "某账期应收最高的客户-产品组合 Top10"),
    ("three_join", "SELECT c.city, ROUND(SUM(b.arrears),2) AS arr FROM fact_bill b JOIN dim_customer c ON c.customer_id=b.customer_id JOIN fact_order o ON o.order_id=b.order_id WHERE b.bill_month BETWEEN '{m1}' AND '{m2}' GROUP BY c.city ORDER BY arr DESC",
     [{"m1": "2026-01", "m2": "2026-06"}, {"m1": "2026-07", "m2": "2026-09"}, {"m1": "2026-06", "m2": "2026-08"}], "某区间各地市欠费合计"),
    ("three_join", "SELECT p.product_type, COUNT(DISTINCT t.ticket_id) AS cnt FROM fact_ticket t JOIN dim_customer c ON c.customer_id=t.customer_id JOIN dim_product p ON p.product_id=t.product_id WHERE c.city LIKE '{city}%' GROUP BY p.product_type",
     [{"city": c} for c in CITIES], "某地市工单按产品类型"),
    ("three_join", "SELECT c.customer_name, p.product_type, ROUND(SUM(b.amount_paid),2) AS paid FROM fact_bill b JOIN dim_customer c ON c.customer_id=b.customer_id JOIN dim_product p ON p.product_id=b.product_id WHERE b.bill_month='{m}' GROUP BY c.customer_name, p.product_type ORDER BY paid DESC LIMIT 5",
     [{"m": x} for x in ("2026-09", "2026-08")], "某账期实收最高客户及产品类型"),
    ("three_join", "SELECT e.team, COUNT(DISTINCT o.order_id) AS cnt FROM fact_order o JOIN dim_employee e ON e.emp_id=o.sales_emp_id JOIN dim_customer c ON c.customer_id=o.customer_id WHERE c.industry='{ind}' GROUP BY e.team ORDER BY cnt DESC LIMIT 5",
     [{"ind": x} for x in ("制造", "金融", "政府", "医疗")], "某行业订单按销售班组分布"),
    # ---------- 聚合 ----------
    ("aggregate", "SELECT city, COUNT(*) AS cnt FROM dim_customer GROUP BY city ORDER BY cnt DESC LIMIT 10",
     [{}], "客户按地市分布"),
    ("aggregate", "SELECT product_type, ROUND(AVG(standard_price),2) AS avg_price FROM dim_product GROUP BY product_type ORDER BY avg_price DESC",
     [{}], "各产品类型平均标准月费"),
    ("aggregate", "SELECT customer_level, COUNT(*) AS cnt FROM dim_customer GROUP BY customer_level ORDER BY cnt DESC",
     [{}], "客户按等级分布"),
    ("aggregate", "SELECT bill_month, ROUND(SUM(amount_due),2) AS due FROM fact_bill GROUP BY bill_month ORDER BY bill_month",
     [{}], "各账期应收合计"),
    ("aggregate", "SELECT handle_team, COUNT(*) AS cnt FROM fact_ticket WHERE resolved_at IS NOT NULL AND (julianday(resolved_at)-julianday(created_at))*24<=4 GROUP BY handle_team ORDER BY cnt DESC, handle_team LIMIT 5",
     [{}], "SLA 达标工单最多的 5 个班组"),
    ("aggregate", "SELECT ticket_type, ROUND(AVG((julianday(first_response_at)-julianday(created_at))*24),2) AS hrs FROM fact_ticket WHERE first_response_at IS NOT NULL GROUP BY ticket_type",
     [{}], "各工单类型平均响应小时数"),
    ("aggregate", "SELECT ROUND(SUM(o.monthly_fee*o.discount_rate),2) AS fee FROM fact_order o JOIN dim_customer c ON c.customer_id=o.customer_id WHERE o.cancel_date IS NULL AND c.industry = '制造'",
     [{}], "行业维度在网订单月费合计"),
    ("aggregate", "SELECT product_name, COUNT(*) AS cnt FROM dim_product GROUP BY product_name HAVING COUNT(*)>1 ORDER BY cnt DESC LIMIT 10",
     [{}], "同名产品组及数量"),
    # ---------- 时间窗口 ----------
    ("time_window", "SELECT bill_month, ROUND(SUM(amount_due),2) AS due FROM fact_bill WHERE bill_month IN ('2026-06','2026-07','2026-08') GROUP BY bill_month ORDER BY bill_month",
     [{}], "最近三个完整账期（不含当月）各月应收"),
    ("time_window", "SELECT substr(bill_month,1,4)||'Q'||((cast(substr(bill_month,6,2) as integer)+2)/3) AS q, ROUND(SUM(amount_due),2) AS due FROM fact_bill WHERE bill_month LIKE '2026-%' GROUP BY q ORDER BY q",
     [{}], "2026 年按季度应收"),
    ("time_window", "SELECT COUNT(*) AS cnt FROM fact_order WHERE order_date>='2026-09-01' AND order_date<='2026-09-30'",
     [{}], "2026 年 9 月新增订单数"),
    ("time_window", "SELECT substr(created_at,1,7) AS mon, COUNT(*) AS cnt FROM fact_ticket WHERE created_at>='2026-01-01' AND ticket_type='故障' GROUP BY mon ORDER BY mon",
     [{}], "2026 年各月故障工单量"),
    ("time_window", "SELECT ROUND(SUM(amount_due),2) AS due FROM fact_bill WHERE bill_month BETWEEN '2026-07' AND '2026-09'",
     [{}], "2026 年三季度应收合计"),
    # ---------- 否定/空值 ----------
    ("negation_null", "SELECT COUNT(*) AS cnt FROM fact_ticket WHERE first_response_at IS NULL",
     [{}], "未响应工单数"),
    ("negation_null", "SELECT COUNT(*) AS cnt FROM fact_ticket WHERE ticket_type='故障' AND resolved_at IS NULL",
     [{}], "未解决的故障工单数"),
    ("negation_null", "SELECT COUNT(*) AS cnt FROM dim_customer WHERE customer_level IS NULL",
     [{}], "等级为空的客户数"),
    ("negation_null", "SELECT COUNT(*) AS cnt FROM fact_order o WHERE o.cancel_date IS NULL AND NOT EXISTS (SELECT 1 FROM fact_bill b WHERE b.order_id=o.order_id)",
     [{}], "在网但从未产生账单的订单数"),
    ("negation_null", "SELECT COUNT(*) AS cnt FROM dim_customer WHERE status<>'正常' AND city LIKE '杭州%'",
     [{}], "杭州非正常状态客户数"),
    ("negation_null", "SELECT b.order_id, b.bill_month FROM fact_bill b JOIN fact_order o ON o.order_id=b.order_id WHERE o.cancel_date IS NOT NULL AND b.bill_month>=substr(o.cancel_date,1,7) LIMIT 10",
     [{}], "退订后仍出账的账单"),
    # ---------- 扩充：单表 ----------
    ("single_hop", "SELECT customer_id, customer_name FROM dim_customer WHERE industry='{ind}' AND status='正常' LIMIT 20",
     [{"ind": x} for x in ("交通", "能源")], "某行业正常客户清单"),
    ("single_hop", "SELECT product_name, standard_price FROM dim_product WHERE product_type='云' AND standard_price>{p} ORDER BY standard_price DESC",
     [{"p": 3000}, {"p": 5000}], "云产品中标准月费超过阈值的产品"),
    ("single_hop", "SELECT order_id, ROUND(monthly_fee*discount_rate,2) AS fee FROM fact_order WHERE discount_rate<{d} ORDER BY fee DESC LIMIT 10",
     [{"d": 0.8}, {"d": 0.75}], "低折扣订单的折扣后月费"),
    ("single_hop", "SELECT ticket_id, urgency FROM fact_ticket WHERE urgency='{u}' AND ticket_type='投诉' LIMIT 10",
     [{"u": "中"}, {"u": "低"}], "某紧急度的投诉工单"),
    ("single_hop", "SELECT emp_name, city FROM dim_employee WHERE city LIKE '{c}%' AND role='客户经理' LIMIT 10",
     [{"c": c} for c in ("杭州", "宁波", "温州")], "某地市客户经理"),
    # ---------- 扩充：两表 ----------
    ("two_join", "SELECT p.product_type, COUNT(*) AS cnt FROM fact_ticket t JOIN dim_product p ON p.product_id=t.product_id JOIN dim_customer c ON c.customer_id=t.customer_id WHERE c.city LIKE '{c}%' GROUP BY p.product_type",
     [{"c": c} for c in ("杭州", "宁波", "温州", "金华", "绍兴")], "某地市工单按产品类型分布"),
    ("two_join", "SELECT c.industry, ROUND(SUM(o.monthly_fee*o.discount_rate),2) AS fee FROM fact_order o JOIN dim_customer c ON c.customer_id=o.customer_id WHERE o.cancel_date IS NULL AND c.industry='{i}' GROUP BY c.industry",
     [{"i": i} for i in ("制造", "金融", "政府", "医疗")], "某行业在网订单折扣后月费合计"),
    ("two_join", "SELECT p.product_type, COUNT(*) AS cnt FROM fact_ticket t JOIN dim_product p ON p.product_id=t.product_id WHERE t.urgency='高' AND p.product_type='{pt}' GROUP BY p.product_type",
     [{"pt": x} for x in ("专线", "云", "IDC")], "某产品类型的高优工单数"),
    ("two_join", "SELECT COUNT(*) AS cnt FROM fact_order o JOIN dim_customer c ON c.customer_id=o.customer_id WHERE o.cancel_date IS NOT NULL AND c.city LIKE '{c}%'",
     [{"c": c} for c in ("杭州", "宁波")], "某地市已退订订单数"),
    # ---------- 扩充：三表 ----------
    ("three_join", "SELECT c.customer_name, ROUND(SUM(b.amount_paid),2) AS paid FROM fact_bill b JOIN dim_customer c ON c.customer_id=b.customer_id WHERE b.bill_month='{m}' GROUP BY c.customer_name ORDER BY paid DESC LIMIT 5",
     [{"m": x} for x in ("2026-07", "2026-05")], "某账期实收 Top5 客户"),
    ("three_join", "SELECT p.product_type, COUNT(DISTINCT t.ticket_id) AS cnt FROM fact_ticket t JOIN dim_customer c ON c.customer_id=t.customer_id JOIN dim_product p ON p.product_id=t.product_id WHERE c.city LIKE '{c}%' GROUP BY p.product_type",
     [{"c": c} for c in ("宁波", "温州", "金华")], "某地市工单按产品类型分布（三表）"),
    # ---------- 扩充：聚合 ----------
    ("aggregate", "SELECT c.city, ROUND(SUM(b.amount_due),2) AS due FROM fact_bill b JOIN dim_customer c ON c.customer_id=b.customer_id WHERE b.bill_month='{m}' GROUP BY c.city ORDER BY due DESC",
     [{"m": x} for x in ("2026-09", "2026-08", "2026-07", "2026-06", "2026-05")], "某账期各地市应收"),
    ("aggregate", "SELECT urgency, COUNT(*) AS cnt FROM fact_ticket GROUP BY urgency ORDER BY cnt DESC",
     [{}], "工单按紧急度分布"),
    ("aggregate", "SELECT status, COUNT(*) AS cnt FROM fact_order GROUP BY status ORDER BY cnt DESC",
     [{}], "订单按状态分布"),
    ("aggregate", "SELECT product_type, COUNT(*) AS cnt FROM dim_product GROUP BY product_type ORDER BY cnt DESC",
     [{}], "产品按类型数量"),
    ("aggregate", "SELECT CASE WHEN adjustment<0 THEN '负调整' WHEN adjustment>0 THEN '正调整' ELSE '无调整' END AS k, COUNT(*) AS cnt FROM fact_bill GROUP BY k",
     [{}], "账单按调整类型分布"),
    ("aggregate", "SELECT substr(sign_date,1,4) AS y, COUNT(*) AS cnt FROM dim_customer GROUP BY y ORDER BY y",
     [{}], "客户按签约年份分布"),
    ("aggregate", "SELECT team, COUNT(*) AS cnt FROM dim_employee GROUP BY team ORDER BY cnt DESC LIMIT 10",
     [{}], "员工按班组分布"),
    ("aggregate", "SELECT handle_team, COUNT(*) AS cnt FROM fact_ticket GROUP BY handle_team ORDER BY cnt DESC LIMIT 5",
     [{}], "工单量最多的 5 个班组"),
    ("aggregate", "SELECT c.industry, ROUND(AVG(b.amount_due),2) AS avg_due FROM fact_bill b JOIN dim_customer c ON c.customer_id=b.customer_id GROUP BY c.industry ORDER BY avg_due DESC",
     [{}], "行业维度平均应收"),
    ("aggregate", "SELECT p.product_type, ROUND(SUM(b.arrears),2) AS arr FROM fact_bill b JOIN dim_product p ON p.product_id=b.product_id GROUP BY p.product_type ORDER BY arr DESC",
     [{}], "产品类型维度欠费合计"),
    ("aggregate", "SELECT customer_level, ROUND(SUM(b.amount_due),2) AS due FROM fact_bill b JOIN dim_customer c ON c.customer_id=b.customer_id GROUP BY customer_level ORDER BY due DESC",
     [{}], "客户等级维度应收"),
    ("aggregate", "SELECT COUNT(DISTINCT customer_id) AS cnt FROM fact_ticket WHERE ticket_type='故障' AND created_at>='2026-01-01'",
     [{}], "2026 年出现故障工单的客户数"),
    # ---------- 扩充：时间窗口 ----------
    ("time_window", "SELECT ROUND(SUM(amount_due),2) AS due FROM fact_bill WHERE bill_month='{m}'",
     [{"m": f"2025-{i:02d}"} for i in range(1, 6)], "某账期应收合计"),
    ("time_window", "SELECT ROUND(SUM(amount_due),2) AS due FROM fact_bill WHERE bill_month='{m}'",
     [{"m": f"2026-{i:02d}"} for i in range(1, 6)], "某账期应收合计"),
    ("time_window", "SELECT substr(bill_month,1,4)||'Q'||((cast(substr(bill_month,6,2) as integer)+2)/3) AS q, ROUND(SUM(amount_due),2) AS due FROM fact_bill WHERE bill_month LIKE '{y}-%' GROUP BY q ORDER BY q",
     [{"y": "2025"}], "2025 年按季度应收"),
    ("time_window", "SELECT COUNT(*) AS cnt FROM fact_ticket WHERE created_at>='{a}' AND created_at<'{b}'",
     [{"a": "2026-01-01", "b": "2026-04-01"}, {"a": "2026-04-01", "b": "2026-07-01"}, {"a": "2026-07-01", "b": "2026-10-01"}], "某季度工单总数"),
    # ---------- 扩充：否定/空值 ----------
    ("negation_null", "SELECT COUNT(*) AS cnt FROM fact_ticket WHERE ticket_type='{t}' AND resolved_at IS NULL",
     [{"t": t} for t in ("投诉", "开通", "故障")], "某类型未解决工单数"),
    ("negation_null", "SELECT COUNT(*) AS cnt FROM dim_customer WHERE customer_level IS NULL AND city LIKE '{c}%'",
     [{"c": c} for c in ("杭州", "宁波", "温州")], "某地市等级为空客户数"),
    ("negation_null", "SELECT COUNT(*) AS cnt FROM fact_order o JOIN dim_product p ON p.product_id=o.product_id WHERE o.cancel_date IS NULL AND p.product_type='{pt}' AND NOT EXISTS (SELECT 1 FROM fact_bill b WHERE b.order_id=o.order_id)",
     [{"pt": t} for t in ("专线", "云", "IDC")], "某产品类型在网但未出账订单数"),
    ("negation_null", "SELECT COUNT(*) AS cnt FROM dim_customer WHERE status<>'正常' AND city LIKE '{c}%'",
     [{"c": c} for c in ("宁波", "温州", "金华", "绍兴")], "某地市非正常客户数"),
    ("aggregate", "SELECT c.city, COUNT(*) AS cnt FROM fact_ticket t JOIN dim_customer c ON c.customer_id=t.customer_id WHERE t.ticket_type='{tt}' GROUP BY c.city ORDER BY cnt DESC",
     [{"tt": t} for t in ("故障", "投诉", "开通")], "某类工单按地市分布"),
    ("aggregate", "SELECT c.city, COUNT(*) AS cnt FROM fact_order o JOIN dim_customer c ON c.customer_id=o.customer_id GROUP BY c.city ORDER BY cnt DESC",
     [{}], "订单按地市分布"),
    ("aggregate", "SELECT ROUND(discount_rate,1) AS d, COUNT(*) AS cnt FROM fact_order GROUP BY d ORDER BY d DESC",
     [{}], "订单按折扣率档位分布"),
    ("aggregate", "SELECT status, COUNT(*) AS cnt FROM dim_product GROUP BY status",
     [{}], "产品按状态分布"),
    ("aggregate", "SELECT p.product_type, ROUND(SUM(b.amount_due),2) AS due FROM fact_bill b JOIN dim_product p ON p.product_id=b.product_id GROUP BY p.product_type ORDER BY due DESC",
     [{}], "产品类型维度应收合计"),
    ("aggregate", "SELECT COUNT(*) AS cnt FROM fact_bill WHERE adjustment<0",
     [{}], "负调整账单数"),
]


def norm_rows(cols: list[str], rows: list[tuple]) -> tuple[list[str], list[list]]:
    out = []
    for r in rows:
        vals = []
        for v in r:
            if isinstance(v, float):
                vals.append(round(v, 2))
            else:
                vals.append(v)
        out.append(vals)
    return cols, out


def main() -> int:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cases: list[dict] = []
    used: dict[str, int] = {k: 0 for k in QUOTA}
    cursor: dict[int, int] = {}

    # 轮转取模板，保证每个模板都被用到，同时按配额收口
    progress = True
    while progress:
        progress = False
        for ti, (split, sql_t, params, hint) in enumerate(TEMPLATES):
            if used[split] >= QUOTA[split]:
                continue
            pi = cursor.get(ti, 0)
            if pi >= len(params):
                continue
            cursor[ti] = pi + 1
            progress = True
            sql = sql_t.format(**params[pi])
            # 不变量：LIMIT 必须有 ORDER BY，否则"前N条"不可判定
            if re.search(r"\blimit\s+\d+", sql, re.IGNORECASE) and "order by" not in sql.lower():
                sql = re.sub(r"\s+limit\s+\d+\s*$", "", sql, flags=re.IGNORECASE)
            try:
                cur = conn.execute(sql)
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
            except Exception as exc:  # noqa: BLE001
                print(f"[skip] 模板 {ti} 第 {pi} 个参数执行失败：{exc}")
                continue
            cols, rows = norm_rows(cols, rows)
            used[split] += 1
            payload = json.dumps([cols, rows], ensure_ascii=False, sort_keys=True)
            cases.append(
                {
                    "qid": f"{split[:2]}-{used[split]:03d}",
                    "split": split,
                    "sql": " ".join(sql.split()),
                    "hint": hint,
                    "columns": cols,
                    "row_count": len(rows),
                    "gold_hash": hashlib.sha256(payload.encode()).hexdigest()[:16],
                    "gold_sample": rows[:5],
                }
            )
    conn.close()

    short = {k: v for k, v in used.items() if v != QUOTA[k]}
    if short:
        print(f"[FAIL] 桶配额未满足：{short}（期望 {QUOTA}）")
        return 2

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n", encoding="utf-8")
    MANIFEST.write_text(
        json.dumps(
            {
                "total": len(cases),
                "by_split": used,
                "quota": QUOTA,
                "sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
                "note": "先执行 SQL 得 gold，再生成问题；EX 只看结果集",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[done] {OUT} 共 {len(cases)} 条")
    print("  分桶：", used)
    return 0


if __name__ == "__main__":
    sys.exit(main())
