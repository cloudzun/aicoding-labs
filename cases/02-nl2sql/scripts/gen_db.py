"""确定性生成 NL2SQL 样例库（seed 固定，任何人重跑得到同一份数据）。

用法：python -m scripts.gen_db
产出：data/aicoding.db、data/manifest.json、db/EMBEDDED_CASES.json
"""

from __future__ import annotations
import sys as _sys

# 干净 Windows 的默认代码页可能不是 UTF-8；中文 print 会抛 UnicodeEncodeError。
if hasattr(_sys.stdout, "reconfigure"):
    _sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import hashlib
import json
import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "aicoding.db"
SCHEMA = ROOT / "db" / "schema.sql"
CASES = ROOT / "db" / "EMBEDDED_CASES.json"
MANIFEST = ROOT / "data" / "manifest.json"

SEED = 20261020
rng = random.Random(SEED)

CITIES = [("杭州", "杭州市"), ("宁波", "宁波市"), ("温州", "温州市"), ("金华", "金华市"), ("绍兴", "绍兴市")]
INDUSTRIES = ["制造", "金融", "政府", "教育", "医疗", "交通", "能源"]
LEVELS = ["A", "B", "C"]
SUFFIX = ["有限公司", "股份有限公司", "集团", "科技股份有限公司"]

# 客户名：城市 + 两字字号 + 行业词 + 公司形式（2026-10-21 去掉名字里的序号，改为"像真的"名字）。
# 字号由 i 确定性派生，**不消耗 rng**，因此其余数据（订单/工单/账单/埋点）与改名前逐值一致。
ZIHAO_A = ["远信", "恒曜", "泓泰", "瑞启", "云栖", "弘澜", "嘉铭", "卓峰", "启元", "泰合",
           "澜庭", "旭诚", "鼎新", "联创", "优博", "诚安", "德华", "科创", "华腾", "联胜"]
ZIHAO_B = ["", "科", "达", "源", "通", "正", "光", "新", "安", "德",
           "胜", "合", "成", "启", "航", "泰", "信", "电", "网", "智"]
IND_NAME = {"制造": "装备制造", "金融": "金融科技", "政府": "政务科技", "教育": "教育科技",
            "医疗": "医疗科技", "交通": "交通建设", "能源": "能源科技"}


def customer_brand(i: int) -> str:
    """确定性字号：i 在 1..400 内唯一，且不消耗随机数。"""
    return ZIHAO_A[(i - 1) // 20] + ZIHAO_B[(i - 1) % 20]

OFFSETS: list[dict] = []


def add_case(code: str, kind: str, desc: str, detect_sql: str, expect: str) -> None:
    OFFSETS.append(
        {"code": code, "type": kind, "desc": desc, "detect_sql": detect_sql, "expect": expect}
    )


def d(dt: date) -> str:
    return dt.strftime("%Y-%m-%d")


def main() -> int:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))

    # ---------- 客户 ----------
    customers: list[tuple] = []
    for i in range(1, 301):
        city, city_full = CITIES[rng.randrange(len(CITIES))]
        # 埋点 B：15% 的客户地市带"市"后缀，形成分组不一致
        city_val = city_full if rng.random() < 0.15 else city
        level = None if rng.random() < 0.03 else rng.choice(LEVELS)  # 埋点 D：3% 等级为空
        status = "正常" if rng.random() > 0.05 else "停用"
        industry = rng.choice(INDUSTRIES)
        # 名称用"城市+字号+行业词+公司形式"，字号由 i 确定性派生 → 唯一且不消耗随机数
        suffix = rng.choice(SUFFIX)
        ind_word = IND_NAME.get(industry, industry)
        if suffix == "科技股份有限公司" and ind_word.endswith("科技"):
            suffix = "股份有限公司"  # 避免"金融科技科技股份有限公司"这类叠词
        customers.append(
            (
                f"C{i:04d}",
                f"{city}{customer_brand(i)}{ind_word}{suffix}",
                industry,
                city_val,
                level,
                d(date(2020 + rng.randrange(5), rng.randrange(1, 13), rng.randrange(1, 28))),
                status,
            )
        )
    # 埋点 A：3 组重复客户（同名同城，不同 ID，均标正常）
    for k, base in enumerate(customers[:3]):
        dup = list(base)
        dup[0] = f"{base[0]}-DUP"
        customers.append(tuple(dup))

    # ---------- 产品 ----------
    products: list[tuple] = []
    pid = 1
    for bw in (10, 20, 50, 100, 200, 500, 1000):
        for _ in range(3):
            products.append(
                (
                    f"P{pid:04d}",
                    f"政企专线-{bw}M",
                    "专线",
                    bw,
                    round(bw * (32 + rng.random() * 8), 2),
                    "在售" if rng.random() > 0.1 else "下架",
                )
            )
            pid += 1
    for name, base in (("政企云-基础版", 1800), ("政企云-标准版", 3200), ("政企云-高级版", 5600)):
        for _ in range(3):
            products.append((f"P{pid:04d}", name, "云", None, round(base * (0.9 + rng.random() * 0.2), 2), "在售"))
            pid += 1
    for name, base in (("IDC-机柜A", 4200), ("IDC-机柜B", 6800), ("IDC-整柜", 15000)):
        for _ in range(2):
            products.append((f"P{pid:04d}", name, "IDC", None, round(base * (0.95 + rng.random() * 0.1), 2), "在售"))
            pid += 1
    # 埋点 C：同名不同规格（专线 100M 与 "政企专线-100M " 同名的另一批），已通过同名多 PID 隐含体现

    # ---------- 员工 ----------
    employees: list[tuple] = []
    for i in range(1, 41):
        city, _ = CITIES[i % len(CITIES)]
        role = "客户经理" if i <= 20 else ("维护班组" if i <= 32 else "客服")
        employees.append((f"E{i:03d}", f"员工{i:03d}", f"{city}{role}组" if role != "客户经理" else f"{city}政企一部", role, city))

    # ---------- 订单 ----------
    start = date(2024, 1, 1)
    end = date(2026, 9, 30)
    span = (end - start).days
    orders: list[tuple] = []
    for i in range(1, 2001):
        cust = customers[rng.randrange(len(customers))]
        prod = products[rng.randrange(len(products))]
        order_date = start + timedelta(days=rng.randrange(span))
        effective = order_date + timedelta(days=rng.randrange(0, 11))
        monthly = round(prod[4] * (0.8 + rng.random() * 0.4), 2)
        discount = round(0.70 + rng.random() * 0.30, 2)
        cancel = None
        status = "待生效" if effective > date(2026, 9, 30) else "在网"
        if rng.random() < 0.15:
            cancel = effective + timedelta(days=rng.randrange(180, 900))
            status = "已退订" if cancel <= date(2026, 9, 30) else "在网"
            if cancel > date(2026, 9, 30):
                cancel = None
        orders.append(
            (
                f"SO{2024 + (i % 3)}{i:06d}" if False else f"SO{i:07d}",
                cust[0],
                prod[0],
                d(order_date),
                d(effective),
                d(cancel) if cancel else None,
                monthly,
                discount,
                employees[rng.randrange(20)][0],
                status,
            )
        )
    # 埋点 E：2 条未来日期（数据错误）
    for idx in (10, 11):
        o = list(orders[idx])
        o[3] = "2027-03-15"
        orders[idx] = tuple(o)

    # ---------- 工单 ----------
    tickets: list[tuple] = []
    t_start = datetime(2025, 1, 1)
    for i in range(1, 5001):
        cust = customers[rng.randrange(len(customers))]
        prod = products[rng.randrange(len(products))]
        created = t_start + timedelta(minutes=rng.randrange((datetime(2026, 9, 30) - t_start).days * 24 * 60))
        ttype = rng.choices(["故障", "投诉", "开通"], weights=[6, 2, 2])[0]
        urgency = rng.choices(["高", "中", "低"], weights=[2, 5, 3])[0]
        # 埋点 F：2.4% 未响应；3% 未解决
        first_resp = created + timedelta(minutes=rng.randrange(3, 480))
        resolved = first_resp + timedelta(minutes=rng.randrange(30, 4320))
        fr = None if rng.random() < 0.024 else first_resp.strftime("%Y-%m-%d %H:%M:%S")
        rv = None if rng.random() < 0.03 else resolved.strftime("%Y-%m-%d %H:%M:%S")
        # 埋点 G：SLA 标记按真实时长算，再人为翻转 0.8% 制造不一致
        sla = "Y" if (resolved - created) <= timedelta(hours=4) else "N"
        if rng.random() < 0.008:
            sla = "N" if sla == "Y" else "Y"
        tickets.append(
            (
                f"TK{i:07d}",
                cust[0],
                prod[0],
                ttype,
                urgency,
                created.strftime("%Y-%m-%d %H:%M:%S"),
                fr,
                rv,
                sla,
                employees[20 + rng.randrange(12)][2],
            )
        )

    # ---------- 账单 ----------
    months = [f"{y}-{m:02d}" for y in (2025, 2026) for m in range(1, 13) if not (y == 2026 and m > 9)]
    bills: dict[tuple, list] = {}  # (month, order_id) -> row
    tries = 0
    while len(bills) < 1200 and tries < 300000:
        tries += 1
        month = months[rng.randrange(len(months))]
        o = orders[rng.randrange(len(orders))]
        order_id, cust_id, prod_id, order_date, eff, cancel = o[0], o[1], o[2], o[3], o[4], o[5]
        if order_date[:7] > month:      # 未下单
            continue
        if eff[:7] > month:             # 未生效
            continue
        if cancel and cancel[:7] < month:  # 已退订
            continue
        key = (month, order_id)
        if key in bills:
            continue
        base = round(o[6] * o[7], 2)
        adj = 0.0 if rng.random() > 0.06 else round(-rng.uniform(10, 300), 2)  # 埋点 I
        due = round(base + adj, 2)
        arrears = 0.0 if rng.random() > 0.2 else round(due * rng.uniform(0.1, 1.0), 2)
        paid = round(due - arrears, 2)
        bills[key] = [month, cust_id, prod_id, due, paid, arrears, adj, order_id]
    # 埋点 H：8 行应收与「月费×折扣+调整」不符（现在能精确对账到订单）
    for k in list(bills.keys())[:8]:
        bills[k][3] = round(bills[k][3] + 3.33, 2)
    # 埋点 J：5 条已退订当月及之后仍出账
    cancelled = [o for o in orders if o[5] and o[5][:7] <= "2026-08"]
    for o in cancelled[:5]:
        month = o[5][:7]
        bills[(month, o[0])] = [month, o[1], o[2], round(o[6] * o[7], 2), 0.0, round(o[6] * o[7], 2), 0.0, o[0]]

    conn.executemany("INSERT INTO dim_customer VALUES (?,?,?,?,?,?,?)", customers)
    conn.executemany("INSERT INTO dim_product VALUES (?,?,?,?,?,?)", products)
    conn.executemany("INSERT INTO dim_employee VALUES (?,?,?,?,?)", employees)
    conn.executemany("INSERT INTO fact_order VALUES (?,?,?,?,?,?,?,?,?,?)", orders)
    conn.executemany("INSERT INTO fact_ticket VALUES (?,?,?,?,?,?,?,?,?,?)", tickets)
    conn.executemany("INSERT INTO fact_bill VALUES (?,?,?,?,?,?,?,?)", list(bills.values()))
    conn.commit()

    # ---------- 埋点登记 ----------
    add_case("A", "重复客户", "3 组客户同名同城，ID 带 -DUP，均标正常", "SELECT customer_name, COUNT(*) c FROM dim_customer GROUP BY customer_name HAVING c>1;", "指标若按客户名去重/计数会偏大")
    add_case("B", "地市名不统一", "约 15% 客户 city 写作『杭州市』等带市后缀", "SELECT city, COUNT(*) FROM dim_customer GROUP BY city ORDER BY 2 DESC;", "按 city 分组会分裂成两个值")
    add_case("C", "产品同名不同规格", "同名产品存在多个 product_id（不同带宽/价格）", "SELECT product_name, COUNT(*) c FROM dim_product GROUP BY product_name HAVING c>1;", "按产品名 JOIN 会放大行数")
    add_case("D", "客户等级为空", "约 3% 客户 customer_level 为 NULL", "SELECT COUNT(*) FROM dim_customer WHERE customer_level IS NULL;", "按等级分组需处理 NULL 桶")
    add_case("E", "订单未来日期", "2 条订单 order_date 为 2027-03-15", "SELECT order_id, order_date FROM fact_order WHERE order_date > date('now');", "时间窗口统计需排除异常日期")
    add_case("F", "工单未响应/未解决", "约 2.4% first_response_at 为空、3% resolved_at 为空", "SELECT COUNT(*) FROM fact_ticket WHERE first_response_at IS NULL;", "平均响应时长计算需排除 NULL")
    add_case("G", "SLA 标记与时长不一致", "约 0.8% 工单 sla_flag 与 (resolved-created)<=4h 矛盾", "SELECT COUNT(*) FROM fact_ticket WHERE (sla_flag='N' AND (julianday(resolved_at)-julianday(created_at))*24<=4) OR (sla_flag='Y' AND (julianday(resolved_at)-julianday(created_at))*24>4);", "以标记为准还是以时长为准，属口径歧义")
    add_case("H", "应收与月费×折扣不符", "8 行 limit 金额被改动 3.33 元", "SELECT b.bill_month, b.order_id, b.amount_due, ROUND(o.monthly_fee*o.discount_rate + b.adjustment,2) calc FROM fact_bill b JOIN fact_order o ON o.order_id=b.order_id WHERE ABS(b.amount_due - (ROUND(o.monthly_fee*o.discount_rate,2)+b.adjustment))>0.01 LIMIT 20;", "校验类问题会命中")
    add_case("I", "负值调整", "约 6% 账单 adjustment 为负", "SELECT COUNT(*) FROM fact_bill WHERE adjustment<0;", "营收口径需说明是否含调整")
    add_case("J", "退订后仍出账", "5 个订单在退订月份仍有账单", "SELECT b.bill_month,b.order_id,o.cancel_date FROM fact_bill b JOIN fact_order o ON o.order_id=b.order_id WHERE o.cancel_date IS NOT NULL AND b.bill_month >= substr(o.cancel_date,1,7) LIMIT 20;", "『在网收入』口径需明确是否按月过滤")

    conn.close()

    counts = {}
    conn = sqlite3.connect(DB_PATH)
    for t in ("dim_customer", "dim_product", "dim_employee", "fact_order", "fact_ticket", "fact_bill"):
        counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    conn.close()

    sha = hashlib.sha256(DB_PATH.read_bytes()).hexdigest()
    MANIFEST.write_text(
        json.dumps(
            {
                "seed": SEED,
                "db": str(DB_PATH.relative_to(ROOT)),
                "sha256": sha,
                "row_counts": counts,
                "total_rows": sum(counts.values()),
                "note": "完全虚构数据，仅用于教学与评测",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    CASES.write_text(json.dumps(OFFSETS, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[done] {DB_PATH}")
    for k, v in counts.items():
        print(f"  {k:14s} {v}")
    print(f"  total          {sum(counts.values())}")
    print(f"  sha256         {sha[:16]}…")
    print(f"[done] 埋点登记 {CASES}（{len(OFFSETS)} 类）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
